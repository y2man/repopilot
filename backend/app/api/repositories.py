from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import current_user, decrypt_credential
from app.core.config import get_settings
from app.ingestion.zip_ingest import ingest_zip, _safe_name
from app.models import User, Repository, RepositoryFile
from app.core.audit import record_audit

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])
def owned_repo(db: Session, repo_id: int, user_id: int) -> Repository:
    repo = db.scalar(select(Repository).where(Repository.id == repo_id, Repository.owner_id == user_id))
    if not repo: raise HTTPException(404, "Repository not found")
    return repo
@router.get("")
def list_repositories(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Repository).where(Repository.owner_id == user.id).order_by(Repository.created_at.desc())).all()
    return [{"id":r.id,"name":r.name,"source":r.source,"status":r.status,"file_count":r.file_count,"chunk_count":r.chunk_count,"created_at":r.created_at,"last_indexed_at":r.last_indexed_at} for r in rows]
@router.post("/upload", status_code=201)
def upload_repository(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not (file.filename or "").lower().endswith(".zip"): raise HTTPException(400, "Please upload a .zip file")
    return _repo_json(ingest_zip(file, user.id, db, get_settings().max_upload_mb * 1024 * 1024))
@router.get("/{repo_id}")
def get_repository(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _repo_json(owned_repo(db, repo_id, user.id))
@router.delete("/{repo_id}", status_code=204)
def delete_repository(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    repo = owned_repo(db, repo_id, user.id)
    record_audit(db, action="repository.deleted", owner_id=user.id, repository_id=repo.id,
        resource_type="repository", resource_id=repo.id, details={"name": repo.name})
    db.delete(repo); db.commit(); return None
@router.get("/{repo_id}/files")
def list_files(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(db, repo_id, user.id)
    files = db.scalars(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id).order_by(RepositoryFile.path)).all()
    return [{"id":f.id,"path":f.path,"language":f.language,"line_count":f.line_count} for f in files]
@router.get("/{repo_id}/files/content")
def read_file(repo_id: int, path: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(db, repo_id, user.id)
    file = db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id, RepositoryFile.path == path))
    if not file: raise HTTPException(404, "File not found")
    return {"path":file.path,"language":file.language,"content":file.content}
def _repo_json(r: Repository):
    return {"id":r.id,"name":r.name,"source":r.source,"status":r.status,"file_count":r.file_count,
        "chunk_count":r.chunk_count,"remote_url":r.remote_url,"remote_ref":r.remote_ref,"created_at":r.created_at,"last_indexed_at":r.last_indexed_at}

# GitHub archive import uses a fixed github.com API host (never a user-supplied fetch URL).
import io, re
from types import SimpleNamespace
from urllib.parse import urlparse, quote
import httpx
from pydantic import BaseModel, Field
from app.models import RepositorySymbol

class GitHubImport(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    ref: str = Field(default="HEAD", min_length=1, max_length=120)

@router.post("/github", status_code=201)
async def import_github(body: GitHubImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    parsed = urlparse(body.url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise HTTPException(400, "Only HTTPS GitHub repository URLs are accepted")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2 or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1].removesuffix(".git")):
        raise HTTPException(400, "Use a GitHub repository URL such as https://github.com/owner/repository")
    owner, repo_name = parts[0], parts[1].removesuffix(".git")
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        github_token = decrypt_credential(user.github_access_token_encrypted) if user.github_access_token_encrypted else settings.github_token
    except Exception as exc:
        raise HTTPException(401, "Stored GitHub authorization is invalid. Reconnect your GitHub account.") from exc
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    raw = bytearray()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            metadata_response = await client.get(f"https://api.github.com/repos/{owner}/{repo_name}", headers=headers)
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            selected_ref = metadata.get("default_branch", "main") if body.ref == "HEAD" else body.ref
            archive_url = f"https://api.github.com/repos/{owner}/{repo_name}/zipball/{quote(selected_ref, safe='')}"
            async with client.stream("GET", archive_url, headers=headers) as response:
                response.raise_for_status()
                if response.headers.get("content-length", "").isdigit() and int(response.headers["content-length"]) > max_bytes:
                    raise HTTPException(413, "GitHub archive exceeds the configured upload limit")
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > max_bytes:
                        raise HTTPException(413, "GitHub archive exceeds the configured upload limit")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        raise HTTPException(404 if code == 404 else 502, "GitHub repository/ref could not be downloaded; check access and ref") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not connect to GitHub") from exc
    upload = SimpleNamespace(filename=f"{repo_name}.zip", file=io.BytesIO(bytes(raw)))
    result = ingest_zip(upload, user.id, db, settings.max_upload_mb * 1024 * 1024, source="github")
    result.remote_url = f"https://github.com/{owner}/{repo_name}"
    result.remote_ref = selected_ref
    db.commit(); db.refresh(result)
    return _repo_json(result)

@router.get("/{repo_id}/symbols")
def list_symbols(repo_id: int, q: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(db, repo_id, user.id)
    query = select(RepositorySymbol).where(RepositorySymbol.repository_id == repo_id)
    if q:
        query = query.where(RepositorySymbol.name.ilike(f"%{q[:100]}%"))
    rows = db.scalars(query.order_by(RepositorySymbol.file_path, RepositorySymbol.start_line).limit(1000)).all()
    return [{"name":s.name,"kind":s.kind,"path":s.file_path,"start_line":s.start_line,
             "end_line":s.end_line,"signature":s.signature} for s in rows]

@router.post("/{repo_id}/reindex", status_code=202)
def reindex_repo(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    repo = owned_repo(db, repo_id, user.id)
    try:
        from app.core.celery_app import celery_app
    except ImportError as exc:
        raise HTTPException(503, "Background indexing worker dependencies are not installed") from exc
    from app.models import IndexingJob
    job = IndexingJob(owner_id=user.id, repository_id=repo.id, status="queued", progress=0, detail="Queued for indexing")
    repo.status = "indexing"
    db.add(job); db.commit(); db.refresh(job)
    try:
        celery_app.send_task("app.tasks.reindex_repository", args=[job.id])
    except Exception as exc:
        job.status = "failed"; job.detail = "Could not enqueue indexing task"; repo.status = "indexing_failed"; db.commit()
        raise HTTPException(503, "Could not reach the indexing queue. Check Redis and the worker service.") from exc
    return {"job_id": job.id, "status": job.status, "progress": job.progress, "detail": job.detail}

@router.get("/{repo_id}/jobs")
def repository_jobs(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(db, repo_id, user.id)
    from app.models import IndexingJob
    rows = db.scalars(select(IndexingJob).where(IndexingJob.repository_id == repo_id,
        IndexingJob.owner_id == user.id).order_by(IndexingJob.created_at.desc()).limit(30)).all()
    return [{"id":j.id,"status":j.status,"progress":j.progress,"detail":j.detail,
             "created_at":j.created_at,"updated_at":j.updated_at} for j in rows]

@router.get("/{repo_id}/export")
def export_repository(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    import zipfile
    from fastapi.responses import StreamingResponse
    from sqlalchemy import select
    repo = owned_repo(db, repo_id, user.id)
    files = db.scalars(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id).order_by(RepositoryFile.path)).all()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            # Ingested paths are normalized and traversal-filtered; keep a final defense at export.
            if _safe_name(file.path): archive.writestr(file.path, file.content)
    buffer.seek(0)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo.name).strip("-.") or "repository"
    return StreamingResponse(buffer, media_type="application/zip",
        headers={"Content-Disposition":f'attachment; filename="{safe_name}-repopilot.zip"'})

from sqlalchemy import select
from datetime import datetime, timezone
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models import IndexingJob, Repository, RepositoryFile, CodeChunk, RepositorySymbol
from app.ingestion.zip_ingest import _line_chunks
from app.ingestion.code_parser import extract_symbols
from app.services.embeddings import embed_texts

@celery_app.task(name="app.tasks.reindex_repository", bind=True, max_retries=1)
def reindex_repository(self, job_id: int):
    db = SessionLocal()
    try:
        job = db.get(IndexingJob, job_id)
        if not job: return {"status": "missing"}
        repo = db.get(Repository, job.repository_id)
        if not repo: job.status = "failed"; job.detail = "Repository no longer exists"; db.commit(); return {"status":"failed"}
        job.status = "running"; job.progress = 2; job.detail = "Loading repository files"; db.commit()
        files = db.scalars(select(RepositoryFile).where(RepositoryFile.repository_id == repo.id)).all()
        db.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).delete(synchronize_session=False)
        db.query(RepositorySymbol).filter(RepositorySymbol.repository_id == repo.id).delete(synchronize_session=False)
        db.commit()
        total = max(1, len(files))
        for index, file in enumerate(files):
            for symbol in extract_symbols(file.path, file.content):
                db.add(RepositorySymbol(repository_id=repo.id, file_path=file.path, **symbol))
            chunks = [CodeChunk(repository_id=repo.id, file_path=file.path, language=file.language,
                start_line=start, end_line=end, content=content)
                for content,start,end in _line_chunks(file.content.splitlines())]
            for offset in range(0, len(chunks), 64):
                batch = chunks[offset:offset+64]
                vectors = embed_texts([c.content for c in batch])
                if vectors:
                    for chunk, vector in zip(batch, vectors): chunk.embedding = vector
                db.add_all(batch)
            job.progress = min(98, int((index + 1) / total * 95) + 2)
            job.detail = f"Indexed {index + 1} of {len(files)} files"
            db.commit()
        repo.chunk_count = db.query(CodeChunk).filter(CodeChunk.repository_id == repo.id).count()
        repo.status = "indexed"
        repo.last_indexed_at = datetime.now(timezone.utc)
        job.status = "completed"; job.progress = 100; job.detail = "Indexing completed"
        db.commit()
        return {"status":"completed", "repository_id":repo.id}
    except Exception as exc:
        db.rollback()
        job = db.get(IndexingJob, job_id)
        if job:
            job.status = "failed"; job.detail = f"Indexing failed: {type(exc).__name__}"
            repo = db.get(Repository, job.repository_id)
            if repo: repo.status = "indexing_failed"
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_github_repository", bind=True, max_retries=1)
def sync_github_repository(self, repository_id: int, ref: str, delivery_id: str):
    """Fetch a fixed-host GitHub archive and replace an existing indexed snapshot."""
    import io
    import httpx
    from types import SimpleNamespace
    from urllib.parse import urlparse, quote
    from app.core.config import get_settings
    from app.core.security import decrypt_credential
    from app.models import User, GitHubWebhookDelivery
    from app.ingestion.zip_ingest import ingest_zip
    from app.core.audit import record_audit

    db = SessionLocal()
    delivery = None
    repo = None
    try:
        delivery = db.scalar(select(GitHubWebhookDelivery).where(
            GitHubWebhookDelivery.delivery_id == delivery_id))
        repo = db.get(Repository, repository_id)
        if not delivery or not repo or repo.source != "github":
            return {"status": "missing"}
        if delivery.status == "completed":
            return {"status": "duplicate"}
        if repo.remote_ref != ref:
            delivery.status = "ignored"
            delivery.detail = "Branch no longer matches the linked repository's tracked ref"
            delivery.processed_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "ignored"}
        parsed = urlparse(repo.remote_url or "")
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parsed.hostname != "github.com" or len(parts) != 2:
            raise ValueError("Stored GitHub repository URL is invalid")
        owner, name = parts
        user = db.get(User, repo.owner_id)
        settings = get_settings()
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = decrypt_credential(user.github_access_token_encrypted) if user and user.github_access_token_encrypted else settings.github_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        max_bytes = settings.max_upload_mb * 1024 * 1024
        archive_url = f"https://api.github.com/repos/{owner}/{name}/zipball/{quote(ref, safe='')}"
        raw = bytearray()
        delivery.status = "running"
        delivery.detail = "Downloading GitHub branch archive"
        db.commit()
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            with client.stream("GET", archive_url, headers=headers) as response:
                response.raise_for_status()
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_bytes:
                    raise ValueError("GitHub archive exceeds configured upload limit")
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > max_bytes:
                        raise ValueError("GitHub archive exceeds configured upload limit")
        upload = SimpleNamespace(filename=f"{name}.zip", file=io.BytesIO(bytes(raw)))
        ingest_zip(upload, repo.owner_id, db, max_bytes, source="github", existing_repo=repo)
        repo.remote_ref = ref
        repo.status = "indexed"
        delivery.status = "completed"
        delivery.detail = "GitHub push synchronized and repository re-indexed"
        delivery.processed_at = datetime.now(timezone.utc)
        record_audit(db, action="github.sync_completed", owner_id=repo.owner_id,
            repository_id=repo.id, resource_type="webhook_delivery", resource_id=delivery_id,
            details={"branch": ref, "file_count": repo.file_count})
        db.commit()
        return {"status": "completed", "repository_id": repo.id}
    except Exception as exc:
        db.rollback()
        if delivery_id:
            delivery = db.scalar(select(GitHubWebhookDelivery).where(
                GitHubWebhookDelivery.delivery_id == delivery_id))
            if delivery:
                delivery.status = "failed"
                delivery.detail = f"GitHub synchronization failed: {type(exc).__name__}"
                delivery.processed_at = datetime.now(timezone.utc)
                record_audit(db, action="github.sync_failed", owner_id=repo.owner_id if repo else None,
                    repository_id=repo.id if repo else None, resource_type="webhook_delivery",
                    resource_id=delivery_id, status="failed", details={"error_type": type(exc).__name__})
        if repo:
            repo = db.get(Repository, repository_id)
            if repo:
                repo.status = "sync_failed"
        db.commit()
        raise
    finally:
        db.close()

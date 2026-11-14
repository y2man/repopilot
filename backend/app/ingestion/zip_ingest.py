import io, re, zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.models import Repository, RepositoryFile, CodeChunk, RepositorySymbol
from app.ingestion.code_parser import extract_symbols
from app.services.embeddings import embed_texts

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__", ".next", "coverage", ".ssh", ".aws", ".azure", ".kube", ".terraform"}
SKIP_NAMES = {".env", ".env.local", ".env.production", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "known_hosts", "authorized_keys", "credentials.json", "secrets.json", "service-account.json", "credentials", "token.json"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".lock", ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".der", ".keystore", ".tfstate"}
LANGS = {".py":"Python", ".ts":"TypeScript", ".tsx":"TSX", ".js":"JavaScript", ".jsx":"JSX", ".go":"Go", ".rs":"Rust", ".java":"Java", ".kt":"Kotlin", ".cs":"C#", ".cpp":"C++", ".c":"C", ".h":"C/C++", ".html":"HTML", ".css":"CSS", ".scss":"SCSS", ".json":"JSON", ".yaml":"YAML", ".yml":"YAML", ".toml":"TOML", ".md":"Markdown", ".sql":"SQL", ".sh":"Shell", ".rb":"Ruby", ".php":"PHP", ".swift":"Swift"}
MAX_FILES = 8000
MAX_FILE_BYTES = 1_000_000
MAX_CHUNK_CHARS = 12_000
SECRET_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{32,}"),
]

def _contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in SECRET_CONTENT_PATTERNS)

def _line_chunks(lines):
    """Yield bounded source chunks with inclusive original line ranges."""
    current = []
    start_line = 1
    chars = 0
    for line_number, line in enumerate(lines, start=1):
        if len(line) > MAX_CHUNK_CHARS:
            if current:
                yield "\n".join(current), start_line, line_number - 1
                current, chars = [], 0
            for offset in range(0, len(line), MAX_CHUNK_CHARS):
                yield line[offset:offset + MAX_CHUNK_CHARS], line_number, line_number
            start_line = line_number + 1
            continue
        if current and (len(current) >= 80 or chars + len(line) + 1 > MAX_CHUNK_CHARS):
            yield "\n".join(current), start_line, line_number - 1
            current, chars = [], 0
            start_line = line_number
        if not current: start_line = line_number
        current.append(line); chars += len(line) + 1
    if current: yield "\n".join(current), start_line, len(lines)

def _safe_name(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and bool(p.parts) and not re.match(r"^[A-Za-z]:", p.parts[0]) and not any(part in SKIP_DIRS for part in p.parts)

def ingest_zip(upload: UploadFile, owner_id: int, db: Session, max_bytes: int, source: str = "zip", existing_repo: Repository | None = None) -> Repository:
    raw = upload.file.read(max_bytes + 1)
    if len(raw) > max_bytes: raise HTTPException(413, f"ZIP exceeds the {max_bytes // (1024*1024)} MB upload limit")
    if not zipfile.is_zipfile(io.BytesIO(raw)): raise HTTPException(400, "Upload must be a valid ZIP archive")
    try: archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc: raise HTTPException(400, "Invalid ZIP archive") from exc
    accepted = []
    seen_paths = set()
    total_uncompressed = 0
    for info in archive.infolist():
        if info.is_dir() or not _safe_name(info.filename): continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000: continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.name.lower() in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES or path.name.lower().startswith((".env", "secret", "credentials")): continue
        if str(path) in seen_paths: continue
        seen_paths.add(str(path))
        if info.file_size > MAX_FILE_BYTES: continue
        total_uncompressed += info.file_size
        if total_uncompressed > max_bytes * 5: raise HTTPException(413, "Expanded ZIP exceeds the safety limit")
        if len(accepted) >= MAX_FILES: raise HTTPException(413, "ZIP contains too many files")
        try:
            data = archive.read(info)
            content = data.decode("utf-8")
        except (UnicodeDecodeError, RuntimeError, zipfile.BadZipFile): continue
        if "\x00" in content or _contains_secret(content): continue
        accepted.append((str(path), content))
    if not accepted: raise HTTPException(400, "No supported text source files found in ZIP")
    name = PurePosixPath(upload.filename or "repository.zip").stem[:255] or "uploaded-repository"
    if existing_repo is not None:
        if existing_repo.owner_id != owner_id:
            raise HTTPException(404, "Repository not found")
        db.query(CodeChunk).filter(CodeChunk.repository_id == existing_repo.id).delete(synchronize_session=False)
        db.query(RepositorySymbol).filter(RepositorySymbol.repository_id == existing_repo.id).delete(synchronize_session=False)
        db.query(RepositoryFile).filter(RepositoryFile.repository_id == existing_repo.id).delete(synchronize_session=False)
        repo = existing_repo
        repo.status = "syncing"
        repo.file_count = 0
        repo.chunk_count = 0
    else:
        repo = Repository(owner_id=owner_id, name=name, source=source, status="indexed", last_indexed_at=datetime.now(timezone.utc))
        db.add(repo)
        db.flush()
    pending_chunks = []
    for path, content in accepted:
        ext = PurePosixPath(path).suffix.lower()
        language = LANGS.get(ext, "text")
        db.add(RepositoryFile(repository_id=repo.id, path=path, language=language, content=content, line_count=max(1, len(content.splitlines()))))
        for symbol in extract_symbols(path, content):
            db.add(RepositorySymbol(repository_id=repo.id, file_path=path, **symbol))
        lines = content.splitlines()
        for chunk_content, start_line, end_line in _line_chunks(lines):
            chunk = CodeChunk(repository_id=repo.id, file_path=path, language=language, start_line=start_line, end_line=end_line, content=chunk_content)
            pending_chunks.append(chunk)
            repo.chunk_count += 1
    # Batch embeddings to keep peak memory bounded on large repositories.
    for offset in range(0, len(pending_chunks), 64):
        batch = pending_chunks[offset:offset + 64]
        vectors = embed_texts([c.content for c in batch])
        if vectors is not None:
            for chunk, vector in zip(batch, vectors): chunk.embedding = vector
        for chunk in batch: db.add(chunk)
        if vectors is None:  # optional model unavailable: do not repeatedly retry each batch
            for chunk in pending_chunks[offset + 64:]: db.add(chunk)
            break
    repo.file_count = len(accepted)
    repo.status = "indexed"
    repo.last_indexed_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(repo)
    return repo

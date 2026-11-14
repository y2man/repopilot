from contextlib import asynccontextmanager
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from threading import Lock
from pathlib import Path
from sqlalchemy import inspect, text
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.repositories import router as repositories_router
from app.api.chat import router as chat_router
from app.api.workflows import router as workflows_router
from app.api.webhooks import router as webhooks_router
from app.api.audit import router as audit_router
from app.core.config import get_settings, normalize_database_url
from app.core.database import Base, engine
import app.models  # register ORM tables

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(message)s")
access_logger = logging.getLogger("repopilot.access")
access_logger.setLevel(logging.INFO)
METRIC_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
METRICS_LOCK = Lock()
HTTP_REQUEST_COUNTS = defaultdict(int)
HTTP_DURATION_SUMS = defaultdict(float)
HTTP_DURATION_BUCKETS = defaultdict(lambda: [0] * len(METRIC_BUCKETS))


def _record_http_metric(method: str, route: str, status: int, duration: float) -> None:
    key = (method, route, status)
    with METRICS_LOCK:
        HTTP_REQUEST_COUNTS[key] += 1
        HTTP_DURATION_SUMS[key] += duration
        for index, bucket in enumerate(METRIC_BUCKETS):
            if duration <= bucket:
                HTTP_DURATION_BUCKETS[key][index] += 1
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env.lower() == "production":
        if settings.secret_key == "development-only-change-me" or len(settings.secret_key) < 32 or settings.secret_key.lower().startswith(("replace-with", "change-me", "dev-")):
            raise RuntimeError("Set a strong SECRET_KEY (at least 32 characters) before production startup")
        production_database_url = normalize_database_url(settings.database_url)
        if not production_database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection string before production startup")
        if any(marker in settings.database_url.lower() for marker in ("repopilot-local-only", "replace-with", "change-me")):
            raise RuntimeError("Replace placeholder credentials in DATABASE_URL before production startup")
        if settings.redis_url.lower().startswith(("redis://localhost", "redis://127.0.0.1")):
            raise RuntimeError("Set REDIS_URL to the production Redis service before production startup")
    if settings.database_url.startswith("sqlite") and settings.app_env.lower() != "production":
        # Local SQLite upgrades are safe to run at startup and keep developer databases current.
        from alembic import command
        from alembic.config import Config
        migration_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        workflow_tables = {"repository_symbols", "conversations", "messages", "agent_executions", "generated_patches", "indexing_jobs"}
        if "users" in tables:
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            repo_columns = {column["name"] for column in inspector.get_columns("repositories")} if "repositories" in tables else set()
            patch_columns = {column["name"] for column in inspector.get_columns("generated_patches")} if "generated_patches" in tables else set()
            if "last_indexed_at" in repo_columns: baseline = "0006_last_indexed"
            elif "is_new_file" in patch_columns: baseline = "0005_new_file_flag"
            elif "remote_url" in repo_columns: baseline = "0004_github_sync"
            elif "github_access_token_encrypted" in user_columns: baseline = "0003_github_oauth"
            elif workflow_tables.issubset(tables): baseline = "0002_workflows"
            else: baseline = "0001_initial"
            if "alembic_version" not in tables:
                command.stamp(migration_config, baseline)
            else:
                with engine.connect() as connection:
                    current = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
                if not current: command.stamp(migration_config, baseline)
        command.upgrade(migration_config, "head")
    elif settings.app_env.lower() == "production":
        # Production schema is migrated once by the release command, never mutated by each API replica.
        with engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        migration_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        expected = ScriptDirectory.from_config(migration_config).get_current_head()
        if current != expected:
            raise RuntimeError(f"Database schema is at {current!r}; expected Alembic head {expected!r}. Run migrations before startup.")
    else:
        Base.metadata.create_all(bind=engine)
    if settings.app_env.lower() == "production":
        from redis.asyncio import from_url
        app.state.redis = from_url(settings.redis_url, decode_responses=True)
        await app.state.redis.ping()
    yield
    if getattr(app.state, "redis", None):
        await app.state.redis.aclose()
app = FastAPI(title=settings.app_name, version="0.2.0", description="Secure repository ingestion and evidence-grounded code intelligence API.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET","POST","PUT","DELETE","OPTIONS"], allow_headers=["Authorization","Content-Type"])
if settings.app_env.lower() == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

@app.middleware("http")
async def production_rate_limit(request, call_next):
    if settings.app_env.lower() != "production":
        response = await call_next(request)
    else:
        path = request.url.path
        limit = (5 if path.endswith("/tests/run") else 10 if path.endswith(("/login", "/register", "/agent/investigate"))
                 else 20 if path.endswith(("/upload", "/github")) else 30 if path.endswith(("/chat", "/review")) else None)
        if limit is not None:
            client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
            key = f"rp:rl:{client_ip}:{path}"
            try:
                count = await request.app.state.redis.incr(key)
                if count == 1: await request.app.state.redis.expire(key, 60)
            except Exception:
                return JSONResponse(status_code=503, content={"detail":"Rate-limit service temporarily unavailable"})
            if count > limit:
                return JSONResponse(status_code=429, content={"detail":"Rate limit exceeded. Retry in one minute."})
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.middleware("http")
async def structured_request_logging(request, call_next):
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if re.fullmatch(r"[A-Za-z0-9._-]{8,64}", supplied) else uuid.uuid4().hex
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration = time.monotonic() - started
        route = getattr(request.scope.get("route"), "path", request.url.path)
        _record_http_metric(request.method, route, 500, duration)
        access_logger.exception(json.dumps({
            "event": "http_request_failed", "request_id": request_id,
            "method": request.method, "path": request.url.path,
            "duration_ms": round(duration * 1000, 2),
            "error_type": type(exc).__name__,
        }))
        raise
    response.headers["X-Request-ID"] = request_id
    route = getattr(request.scope.get("route"), "path", request.url.path)
    duration = time.monotonic() - started
    _record_http_metric(request.method, route, response.status_code, duration)
    access_logger.info(json.dumps({
        "event": "http_request", "request_id": request_id,
        "method": request.method, "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": round(duration * 1000, 2),
    }))
    return response


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    lines = [
        "# HELP repopilot_http_requests_total Total HTTP requests handled by the API.",
        "# TYPE repopilot_http_requests_total counter",
    ]
    with METRICS_LOCK:
        counts = list(HTTP_REQUEST_COUNTS.items())
        sums = dict(HTTP_DURATION_SUMS)
        buckets = {key: list(value) for key, value in HTTP_DURATION_BUCKETS.items()}
    for (method, route, status), count in counts:
        labels = f'method="{method}",route="{route}",status="{status}"'
        lines.append(f"repopilot_http_requests_total{{{labels}}} {count}")
    lines.extend([
        "# HELP repopilot_http_request_duration_seconds HTTP request duration in seconds.",
        "# TYPE repopilot_http_request_duration_seconds histogram",
    ])
    for key, count in counts:
        method, route, status = key
        labels = f'method="{method}",route="{route}",status="{status}"'
        for index, bucket in enumerate(METRIC_BUCKETS):
            lines.append(f'repopilot_http_request_duration_seconds_bucket{{{labels},le="{bucket}"}} {buckets[key][index]}')
        lines.append(f'repopilot_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}')
        lines.append(f'repopilot_http_request_duration_seconds_sum{{{labels}}} {sums[key]}')
        lines.append(f'repopilot_http_request_duration_seconds_count{{{labels}}} {count}')
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4; charset=utf-8")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(repositories_router)
app.include_router(chat_router)
app.include_router(workflows_router)
app.include_router(webhooks_router)
app.include_router(audit_router)
@app.get("/", include_in_schema=False)
async def root(): return {"name":settings.app_name,"docs":"/docs","health":"/health","api":"/api/v1"}

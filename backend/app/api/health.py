from fastapi import APIRouter, Request
from sqlalchemy import text
from app.core.database import engine
from app.core.config import get_settings
from importlib.util import find_spec
router = APIRouter(tags=["system"])

@router.get("/health", summary="Service health")
async def health(request: Request):
    settings = get_settings()
    db_status = "ok"
    try:
        with engine.connect() as connection: connection.execute(text("SELECT 1"))
    except Exception: db_status = "unavailable"
    redis_status = "not_required"
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            await redis.ping(); redis_status = "ok"
        except Exception: redis_status = "unavailable"
    status = "ok" if db_status == "ok" and redis_status in {"ok", "not_required"} else "degraded"
    vector_store = "pgvector" if engine.dialect.name == "postgresql" else "sqlite-no-vector-extension"
    return {"status":status,"service":"repopilot-api","database":db_status,
        "redis":redis_status,"vector_store":vector_store,
        "ai_configured":bool(settings.groq_api_key),
        "embeddings_installed":find_spec("sentence_transformers") is not None,
        "tree_sitter_installed":find_spec("tree_sitter_language_pack") is not None,
        "reranker_enabled":settings.reranker_enabled,
        "github_oauth_configured":bool(settings.github_client_id and settings.github_client_secret)}

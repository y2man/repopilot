"""Authenticated GitHub webhook intake with delivery idempotency."""
import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import GitHubWebhookDelivery, Repository
from app.core.audit import record_audit

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def enqueue_github_sync(repository_id: int, branch: str, delivery_id: str) -> None:
    from app.core.celery_app import celery_app
    celery_app.send_task("app.tasks.sync_github_repository", args=[repository_id, branch, delivery_id])


@router.post("/github", status_code=202)
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    settings = get_settings()
    if not settings.github_webhook_secret:
        raise HTTPException(503, "GitHub webhook integration is not configured")
    if not x_github_delivery or len(x_github_delivery) > 255:
        raise HTTPException(400, "Missing or invalid GitHub delivery ID")
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "Webhook payload is too large")
    digest = hmac.new(settings.github_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not x_hub_signature_256 or not hmac.compare_digest(x_hub_signature_256, expected):
        raise HTTPException(401, "Invalid GitHub webhook signature")
    if x_github_event != "push":
        return {"accepted": True, "ignored": True, "reason": "Only push events are processed"}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid GitHub webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "GitHub webhook payload must be a JSON object")
    if payload.get("deleted") is True:
        return {"accepted": True, "ignored": True, "reason": "Deleted branches are not synchronized"}
    ref = payload.get("ref", "")
    if not isinstance(ref, str) or not ref.startswith("refs/heads/"):
        return {"accepted": True, "ignored": True, "reason": "Only branch push events are processed"}
    branch = ref.removeprefix("refs/heads/")
    repository_data = payload.get("repository")
    remote_url = repository_data.get("html_url", "") if isinstance(repository_data, dict) else ""
    parsed = urlparse(remote_url if isinstance(remote_url, str) else "")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2:
        return {"accepted": True, "ignored": True, "reason": "Unsupported repository URL"}
    canonical_url = f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}"
    repo = db.scalar(select(Repository).where(
        Repository.source == "github",
        func.lower(Repository.remote_url) == canonical_url.lower(),
        Repository.remote_ref == branch,
    ))
    if not repo:
        return {"accepted": True, "ignored": True, "reason": "No linked RepoPilot repository tracks this branch"}

    delivery = db.scalar(select(GitHubWebhookDelivery).where(
        GitHubWebhookDelivery.delivery_id == x_github_delivery))
    if delivery and delivery.repository_id != repo.id:
        raise HTTPException(409, "GitHub delivery ID is already associated with another repository")
    if delivery and delivery.status in {"queued", "running", "completed"}:
        return {"accepted": True, "duplicate": True, "status": delivery.status}
    if delivery:
        delivery.status = "queued"
        delivery.detail = "Webhook delivery retried after previous enqueue failure"
        delivery.processed_at = None
    else:
        delivery = GitHubWebhookDelivery(delivery_id=x_github_delivery,
            repository_id=repo.id, event="push", status="queued")
        db.add(delivery)
    repo.status = "syncing"
    record_audit(db, action="github.webhook_queued", owner_id=repo.owner_id,
        repository_id=repo.id, resource_type="webhook_delivery", resource_id=x_github_delivery,
        details={"branch": branch})
    db.commit()
    try:
        enqueue_github_sync(repo.id, branch, x_github_delivery)
    except Exception as exc:
        delivery.status = "failed"
        delivery.detail = "Could not enqueue GitHub synchronization task"
        delivery.processed_at = datetime.now(timezone.utc)
        repo.status = "sync_failed"
        db.commit()
        raise HTTPException(503, "Could not queue GitHub synchronization; GitHub may retry this delivery") from exc
    return {"accepted": True, "repository_id": repo.id, "status": "queued"}

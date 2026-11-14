import hashlib
import hmac
import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.core.database import SessionLocal
from app.models import GitHubWebhookDelivery, Repository


def create_linked_repo(client):
    email = f"hook-{uuid.uuid4().hex}@example.com"
    auth = client.post("/api/v1/auth/register", json={
        "email": email, "password": "secure-webhook-test-password-123"})
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
    from app.models import User
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        slug = uuid.uuid4().hex
        remote = f"https://github.com/example/{slug}"
        repo = Repository(owner_id=user.id, name=slug, source="github",
            remote_url=remote, remote_ref="main", status="indexed")
        db.add(repo); db.commit(); db.refresh(repo)
        return headers, repo.id, remote


def signed_headers(body, delivery_id="delivery-001"):
    secret = "webhook-unit-test-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "push",
    }


def test_github_webhook_signature_is_required(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings(); settings.github_webhook_secret = "webhook-unit-test-secret"
    monkeypatch.setattr("app.api.webhooks.get_settings", lambda: settings)
    with TestClient(app) as client:
        response = client.post("/api/v1/webhooks/github", content=b"{}",
            headers={"X-GitHub-Delivery":"x", "X-GitHub-Event":"push",
                     "X-Hub-Signature-256":"sha256=invalid"})
        assert response.status_code == 401


def test_github_push_webhook_queues_one_idempotent_sync(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings(); settings.github_webhook_secret = "webhook-unit-test-secret"
    monkeypatch.setattr("app.api.webhooks.get_settings", lambda: settings)
    queued = []
    monkeypatch.setattr("app.api.webhooks.enqueue_github_sync",
        lambda repo_id, branch, delivery: queued.append((repo_id, branch, delivery)))
    with TestClient(app) as client:
        _, repo_id, remote_url = create_linked_repo(client)
        body = json.dumps({"ref":"refs/heads/main", "deleted":False,
            "repository":{"html_url":remote_url}}).encode()
        delivery_id = f"delivery-{uuid.uuid4().hex}"
        headers = signed_headers(body, delivery_id)
        first = client.post("/api/v1/webhooks/github", content=body, headers=headers)
        second = client.post("/api/v1/webhooks/github", content=body, headers=headers)
        assert first.status_code == 202 and first.json()["status"] == "queued"
        assert second.status_code == 202 and second.json()["duplicate"] is True
    assert len(queued) == 1
    assert queued[0] == (repo_id, "main", delivery_id)
    with SessionLocal() as db:
        delivery = db.scalar(select(GitHubWebhookDelivery).where(
            GitHubWebhookDelivery.delivery_id == delivery_id))
        repo = db.get(Repository, repo_id)
        assert delivery.status == "queued" and repo.status == "syncing"


def test_github_webhook_ignores_untracked_branch(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings(); settings.github_webhook_secret = "webhook-unit-test-secret"
    monkeypatch.setattr("app.api.webhooks.get_settings", lambda: settings)
    with TestClient(app) as client:
        _, _, remote_url = create_linked_repo(client)
        body = json.dumps({"ref":"refs/heads/feature", "deleted":False,
            "repository":{"html_url":remote_url}}).encode()
        response = client.post("/api/v1/webhooks/github", content=body,
            headers=signed_headers(body, "delivery-untracked"))
        assert response.status_code == 202 and response.json()["ignored"] is True

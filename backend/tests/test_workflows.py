import io, uuid, zipfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ingestion.code_parser import extract_symbols


def archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("demo/src/auth.py", "def authenticate(user, password):\n    return password == 'ok'\n\nclass AuthService:\n    pass\n")
    return stream.getvalue()


def auth_client(client):
    email = f"workflow-{uuid.uuid4().hex}@example.com"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": "secure-test-password-123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload(client, headers):
    response = client.post("/api/v1/repositories/upload", headers=headers,
        files={"file": ("demo.zip", archive(), "application/zip")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_python_ast_symbols_include_function_and_class():
    rows = extract_symbols("pkg/auth.py", "def login(x):\n return x\n\nclass Auth:\n pass\n")
    assert {r["name"] for r in rows} == {"login", "Auth"}
    assert next(r for r in rows if r["name"] == "login")["start_line"] == 1


def test_symbols_api_and_github_url_validation():
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        symbols = client.get(f"/api/v1/repositories/{repo_id}/symbols", headers=headers)
        assert symbols.status_code == 200
        assert {s["name"] for s in symbols.json()} >= {"authenticate", "AuthService"}
        invalid = client.post("/api/v1/repositories/github", headers=headers,
            json={"url":"https://example.com/owner/repo"})
        assert invalid.status_code == 400


def test_agent_investigation_is_persisted_and_owner_scoped(monkeypatch):
    async def fake_answer(question, sources):
        return "Authentication is handled by the indexed authenticate function [demo/src/auth.py:1-2]."
    monkeypatch.setattr("app.api.workflows.answer", fake_answer)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        result = client.post("/api/v1/agent/investigate", headers=headers,
            json={"repository_id":repo_id,"task":"Trace authenticate function"})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "completed"
        history = client.get(f"/api/v1/agent/executions?repository_id={repo_id}", headers=headers)
        assert history.status_code == 200 and len(history.json()) == 1
        assert history.json()[0]["result"].startswith("Authentication")


def test_patch_requires_explicit_approval_and_updates_snapshot(monkeypatch):
    async def fake_json(system, payload):
        return {"proposed_content":"def authenticate(user, password):\n    return False\n\nclass AuthService:\n    pass\n",
                "explanation":"Example proposed change"}
    monkeypatch.setattr("app.api.workflows.complete_json", fake_json)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        proposal = client.post("/api/v1/patches/propose", headers=headers,
            json={"repository_id":repo_id,"file_path":"demo/src/auth.py","instruction":"Change authentication to always fail for test"})
        assert proposal.status_code == 200, proposal.text
        patch = proposal.json()
        assert patch["status"] == "pending" and "-    return password" in patch["diff"]
        approved = client.post(f"/api/v1/patches/{patch['id']}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved_applied"
        content = client.get(f"/api/v1/repositories/{repo_id}/files/content?path=demo%2Fsrc%2Fauth.py", headers=headers)
        assert "return False" in content.json()["content"]


def test_patch_rejects_stale_source(monkeypatch):
    async def fake_json(system, payload):
        return {"proposed_content":"changed\n", "explanation":"test"}
    monkeypatch.setattr("app.api.workflows.complete_json", fake_json)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        proposal = client.post("/api/v1/patches/propose", headers=headers,
            json={"repository_id":repo_id,"file_path":"demo/src/auth.py","instruction":"Rewrite file"}).json()
        # Applying a stale proposal must fail closed; modifying through a patch is intentionally not exposed here.
        from app.core.database import SessionLocal
        from app.models import RepositoryFile
        from sqlalchemy import select
        with SessionLocal() as db:
            file = db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id))
            file.content += "# changed\n"; db.commit()
        response = client.post(f"/api/v1/patches/{proposal['id']}/approve", headers=headers)
        assert response.status_code == 409


def test_chat_conversation_persists_followups(monkeypatch):
    async def fake_answer(question, sources): return f"Evidence response for: {question}"
    monkeypatch.setattr("app.api.chat.answer", fake_answer)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        first = client.post("/api/v1/chat", headers=headers,
            json={"repository_id":repo_id,"question":"Explain authentication"})
        assert first.status_code == 200
        conversation_id = first.json()["conversation_id"]
        second = client.post("/api/v1/chat", headers=headers,
            json={"repository_id":repo_id,"question":"What about the class?","conversation_id":conversation_id})
        assert second.status_code == 200 and second.json()["conversation_id"] == conversation_id
        history = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        assert [m["role"] for m in history.json()] == ["user", "assistant", "user", "assistant"]


def test_repository_export_contains_indexed_snapshot():
    import zipfile
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        response = client.get(f"/api/v1/repositories/{repo_id}/export", headers=headers)
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            assert "demo/src/auth.py" in z.namelist()
            assert "def authenticate" in z.read("demo/src/auth.py").decode()


def test_github_credential_encryption_round_trip():
    from app.core.security import encrypt_credential, decrypt_credential
    token = "gho_test_token_value_not_real"
    encrypted = encrypt_credential(token)
    assert encrypted != token
    assert decrypt_credential(encrypted) == token


def test_patch_publish_requires_approved_github_patch():
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        # ZIP repositories cannot be published to GitHub, and an unapproved patch cannot be pushed.
        from app.core.database import SessionLocal
        from app.models import GeneratedPatch
        with SessionLocal() as db:
            patch = GeneratedPatch(owner_id=int(client.get('/api/v1/auth/me',headers=headers).json()['id']),
                repository_id=repo_id,file_path='demo/src/auth.py',original_content='x',
                proposed_content='y',explanation='test',status='pending')
            db.add(patch); db.commit(); db.refresh(patch); patch_id=patch.id
        response = client.post(f"/api/v1/patches/{patch_id}/publish", headers=headers)
        assert response.status_code == 409


def test_chat_stream_persists_completed_assistant_response(monkeypatch):
    from types import SimpleNamespace
    async def fake_stream(question, sources):
        yield "Streamed "
        yield "answer"
    monkeypatch.setattr("app.api.chat.get_settings", lambda: SimpleNamespace(groq_api_key="configured"))
    monkeypatch.setattr("app.api.chat.stream_answer", fake_stream)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        response = client.post("/api/v1/chat/stream", headers=headers,
            json={"repository_id":repo_id,"question":"Explain authentication"})
        assert response.status_code == 200
        assert response.text.index('"status": "retrieving"') < response.text.index('"status": "generating"')
        assert response.text.index('"status": "generating"') < response.text.index('"token": "Streamed "')
        assert '"token": "Streamed "' in response.text
        assert '"done": true' in response.text


def test_generated_tests_are_pending_until_approved(monkeypatch):
    async def fake_json(system, payload):
        return {"proposed_content":"def test_authenticate():\n    assert True\n", "explanation":"Basic smoke test"}
    monkeypatch.setattr("app.api.workflows.complete_json", fake_json)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        generated = client.post("/api/v1/tests/generate", headers=headers,
            json={"repository_id":repo_id,"source_file_path":"demo/src/auth.py",
                  "test_file_path":"tests/test_auth.py"})
        assert generated.status_code == 200, generated.text
        proposal = generated.json()
        assert proposal["status"] == "pending"
        files_before = client.get(f"/api/v1/repositories/{repo_id}/files", headers=headers).json()
        assert "tests/test_auth.py" not in {f["path"] for f in files_before}
        approved = client.post(f"/api/v1/patches/{proposal['id']}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        files_after = client.get(f"/api/v1/repositories/{repo_id}/files", headers=headers).json()
        assert "tests/test_auth.py" in {f["path"] for f in files_after}


def test_python_test_runner_requires_explicit_sandbox_configuration(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    settings.sandbox_shared_secret = ""
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        response = client.post("/api/v1/tests/run", headers=headers, json={"repository_id": repo_id})
        assert response.status_code == 503
        assert "SANDBOX_SHARED_SECRET" in response.json()["detail"]


def test_python_test_runner_is_user_scoped():
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        other = auth_client(client)
        response = client.post("/api/v1/tests/run", headers=other, json={"repository_id": repo_id})
        assert response.status_code == 404


def test_python_test_runner_sends_snapshot_and_persists_result(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    settings.sandbox_shared_secret = "unit-test-runner-secret"
    settings.sandbox_url = "http://sandbox:8090"
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    captured = {}

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"status":"passed","exit_code":0,"output":"2 passed in 0.01s",
                    "duration_seconds":0.21,"timed_out":False}

    class FakeClient:
        def __init__(self, **kwargs): self.kwargs = kwargs
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, url, json, headers):
            captured.update(url=url, payload=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        response = client.post("/api/v1/tests/run", headers=headers,
            json={"repository_id":repo_id,"timeout_seconds":30})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "passed"
        assert captured["url"] == "http://sandbox:8090/v1/tests/python"
        assert captured["headers"]["Authorization"] == "Bearer unit-test-runner-secret"
        assert len(captured["payload"]["archive_b64"]) > 10
        history = client.get(f"/api/v1/agent/executions?repository_id={repo_id}", headers=headers)
        assert any(row["status"] == "passed" and "2 passed" in row["result"] for row in history.json())


def test_applied_patch_can_be_rolled_back_to_exact_original_snapshot(monkeypatch):
    async def fake_json(system, payload):
        return {"proposed_content":"def authenticate(user, password):\n    return False\n",
                "explanation":"Temporary change"}
    monkeypatch.setattr("app.api.workflows.complete_json", fake_json)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        original = client.get(f"/api/v1/repositories/{repo_id}/files/content?path=demo%2Fsrc%2Fauth.py", headers=headers).json()["content"]
        proposal = client.post("/api/v1/patches/propose", headers=headers,
            json={"repository_id":repo_id,"file_path":"demo/src/auth.py","instruction":"Temporarily change auth"}).json()
        applied = client.post(f"/api/v1/patches/{proposal['id']}/approve", headers=headers)
        assert applied.status_code == 200
        rollback = client.post(f"/api/v1/patches/{proposal['id']}/rollback", headers=headers)
        assert rollback.status_code == 200 and rollback.json()["status"] == "rolled_back"
        restored = client.get(f"/api/v1/repositories/{repo_id}/files/content?path=demo%2Fsrc%2Fauth.py", headers=headers)
        assert restored.json()["content"] == original


def test_rollback_refuses_to_overwrite_newer_snapshot_content(monkeypatch):
    async def fake_json(system, payload):
        return {"proposed_content":"def authenticate():\n    return True\n", "explanation":"change"}
    monkeypatch.setattr("app.api.workflows.complete_json", fake_json)
    with TestClient(app) as client:
        headers = auth_client(client)
        repo_id = upload(client, headers)
        proposal = client.post("/api/v1/patches/propose", headers=headers,
            json={"repository_id":repo_id,"file_path":"demo/src/auth.py","instruction":"Change file"}).json()
        client.post(f"/api/v1/patches/{proposal['id']}/approve", headers=headers)
        from app.core.database import SessionLocal
        from app.models import RepositoryFile
        from sqlalchemy import select
        with SessionLocal() as db:
            file = db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id))
            file.content = "concurrent newer change\n"
            db.commit()
        response = client.post(f"/api/v1/patches/{proposal['id']}/rollback", headers=headers)
        assert response.status_code == 409


def test_published_github_patch_revert_uses_conflict_checked_new_commit(monkeypatch):
    import base64
    from app.core.database import SessionLocal
    from app.core.security import encrypt_credential
    from app.models import GeneratedPatch, Repository, RepositoryFile, User
    from sqlalchemy import select

    original = "def hello():\n    return 'before'\n"
    proposed = "def hello():\n    return 'after'\n"
    with TestClient(app) as client:
        headers = auth_client(client)
        user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.github_access_token_encrypted = encrypt_credential("gho_mock_token")
            repo = Repository(owner_id=user_id, name="demo", source="github",
                remote_url="https://github.com/example/demo", remote_ref="main", status="indexed")
            db.add(repo); db.flush()
            file = RepositoryFile(repository_id=repo.id, path="src/hello.py", language="python",
                content=proposed, line_count=2)
            db.add(file); db.flush()
            patch = GeneratedPatch(owner_id=user_id, repository_id=repo.id, file_path=file.path,
                original_content=original, proposed_content=proposed, explanation="test",
                status="published", published_commit_url="https://github.com/example/demo/commit/abc")
            db.add(patch); db.commit(); patch_id=patch.id; repo_id=repo.id

        class Response:
            status_code = 200
            def __init__(self, data): self.data=data
            def json(self): return self.data
            def raise_for_status(self): return None
        class FakeClient:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def get(self, url, params, headers):
                return Response({"sha":"remote-sha","content":base64.b64encode(proposed.encode()).decode()})
            async def put(self, url, headers, json):
                assert base64.b64decode(json["content"]).decode() == original
                assert json["sha"] == "remote-sha" and json["branch"] == "main"
                return Response({"commit":{"html_url":"https://github.com/example/demo/commit/revert"}})
        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        response = client.post(f"/api/v1/patches/{patch_id}/revert-github", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "reverted"
        assert response.json()["commit_url"].endswith("/revert")
        with SessionLocal() as db:
            file = db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id == repo_id))
            assert file.content == original

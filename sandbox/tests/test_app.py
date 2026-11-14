import io
import tarfile

import pytest
from fastapi.testclient import TestClient

from app import app as sandbox_app
from app import _extract_validated


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in entries:
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_snapshot_extraction_keeps_nested_files(tmp_path):
    count = _extract_validated(archive([("repo/tests/test_ok.py", "def test_ok(): pass")]), str(tmp_path))
    assert count == 1
    assert (tmp_path / "repo/tests/test_ok.py").read_text() == "def test_ok(): pass"


@pytest.mark.parametrize("path", ["../escape.py", "/absolute.py", "repo/../../escape.py"])
def test_snapshot_rejects_traversal_paths(tmp_path, path):
    with pytest.raises(Exception):
        _extract_validated(archive([(path, "nope")]), str(tmp_path))
    assert not (tmp_path.parent / "escape.py").exists()


def test_snapshot_rejects_symbolic_links(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("repo/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../etc/passwd"
        tar.addfile(info)
    with pytest.raises(Exception):
        _extract_validated(buffer.getvalue(), str(tmp_path))


def test_runner_requires_authentication(monkeypatch):
    monkeypatch.setattr("app.SHARED_SECRET", "test-secret")
    with TestClient(sandbox_app) as client:
        response = client.post("/v1/tests/python", json={"archive_b64": "dGVzdA=="})
        assert response.status_code == 401
        ok = client.post("/v1/tests/python", headers={"Authorization": "Bearer test-secret"},
                         json={"archive_b64": "dGVzdA=="})
        # Auth succeeds and the base64 is valid, then runtime readiness is checked.
        assert ok.status_code in {400, 503}


def test_execution_uses_fixed_command_and_hardened_container(monkeypatch):
    import base64
    import sys
    import types

    monkeypatch.setattr("app.SHARED_SECRET", "test-secret")
    observed = {}

    class DockerException(Exception): pass
    class ImageNotFound(DockerException): pass

    class FakeExec:
        exit_code = 0
        output = b"1 passed in 0.01s"

    class FakeContainer:
        def start(self): observed["started"] = True
        def put_archive(self, path, data):
            observed["archive_path"] = path
            observed["archive_bytes"] = len(data)
            return True
        def exec_run(self, command, **kwargs):
            observed["test_command"] = command
            observed["exec_kwargs"] = kwargs
            return FakeExec()
        def kill(self): observed["killed"] = True
        def remove(self, force=False): observed["removed"] = force

    class FakeContainers:
        def create(self, image, **kwargs):
            observed["image"] = image
            observed["container_kwargs"] = kwargs
            return FakeContainer()

    class FakeImages:
        def get(self, image): observed["image_checked"] = image

    class FakeClient:
        containers = FakeContainers()
        images = FakeImages()
        def ping(self): return True

    docker_module = types.ModuleType("docker")
    docker_module.__path__ = []
    docker_module.from_env = lambda **kwargs: FakeClient()
    errors_module = types.ModuleType("docker.errors")
    errors_module.DockerException = DockerException
    errors_module.ImageNotFound = ImageNotFound
    docker_module.errors = errors_module
    monkeypatch.setitem(sys.modules, "docker", docker_module)
    monkeypatch.setitem(sys.modules, "docker.errors", errors_module)

    payload = base64.b64encode(archive([("tests/test_ok.py", "def test_ok(): pass")])).decode()
    with TestClient(sandbox_app) as client:
        response = client.post("/v1/tests/python", headers={"Authorization":"Bearer test-secret"},
                               json={"archive_b64":payload,"timeout_seconds":5})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "passed"
    settings = observed["container_kwargs"]
    assert settings["network_mode"] == "none"
    assert settings["read_only"] is True
    assert settings["tmpfs"]["/workspace"].endswith("size=128m")
    assert settings["mem_limit"] == "512m" and settings["pids_limit"] == 64
    assert settings["cap_drop"] == ["ALL"]
    assert settings["security_opt"] == ["no-new-privileges:true"]
    assert settings["user"] == "10001:10001"
    assert observed["test_command"] == ["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    assert observed["archive_path"] == "/workspace"
    assert observed["removed"] is True

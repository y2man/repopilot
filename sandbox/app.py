"""Trusted control plane for disposable, network-isolated test containers.

This service must never execute repository content in its own process. It only
validates requests and asks the Docker daemon to start a fixed, constrained
runner image. Keep this service private and on a dedicated host/VM in production:
access to the Docker socket is effectively host-root access.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import io
import os
import tarfile
import tempfile
import threading
import time
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="RepoPilot Isolated Test Runner", docs_url=None, redoc_url=None)
JOB_SLOTS = threading.BoundedSemaphore(2)
SHARED_SECRET = os.environ.get("SANDBOX_SHARED_SECRET", "")
RUNNER_IMAGE = os.environ.get("SANDBOX_RUNNER_IMAGE", "repopilot-test-python:3.12")
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_FILES = 2500
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_EXPANDED = 50 * 1024 * 1024
MAX_RUNTIME_SECONDS = 90


class TestRunRequest(BaseModel):
    archive_b64: str = Field(min_length=4, max_length=28_000_000)
    timeout_seconds: int = Field(default=45, ge=5, le=MAX_RUNTIME_SECONDS)


class TestRunResponse(BaseModel):
    status: str
    exit_code: int | None
    output: str
    duration_seconds: float
    timed_out: bool = False


def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
    if not SHARED_SECRET:
        raise HTTPException(503, "Sandbox authentication is not configured")
    expected = f"Bearer {SHARED_SECRET}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Unauthorized")


def _extract_validated(archive_bytes: bytes, destination: str) -> int:
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, "Repository snapshot exceeds sandbox upload limit")
    count = 0
    expanded = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_FILES:
                raise HTTPException(413, "Repository contains too many files for a test run")
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or not path.parts or any(p in {"..", ""} for p in path.parts):
                    raise HTTPException(400, "Unsafe path in repository snapshot")
                if not (member.isfile() or member.isdir()):
                    raise HTTPException(400, "Links and special files are not allowed in sandbox snapshots")
                if member.size > MAX_FILE_BYTES:
                    raise HTTPException(413, "A repository file exceeds the sandbox file limit")
                expanded += member.size
                if expanded > MAX_TOTAL_EXPANDED:
                    raise HTTPException(413, "Expanded repository snapshot exceeds sandbox limit")
                if member.isfile():
                    count += 1
                    source = archive.extractfile(member)
                    if source is None:
                        raise HTTPException(400, "Invalid repository archive entry")
                    target = os.path.realpath(os.path.join(destination, *path.parts))
                    if os.path.commonpath([destination, target]) != destination:
                        raise HTTPException(400, "Unsafe path in repository snapshot")
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "xb") as output:
                        output.write(source.read(MAX_FILE_BYTES + 1))
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise HTTPException(400, "Invalid repository snapshot archive") from exc
    return count


@app.get("/health")
def health():
    return {"status": "ok", "runner_image": RUNNER_IMAGE}


@app.post("/v1/tests/python", response_model=TestRunResponse, dependencies=[Depends(authorize)])
def run_python_tests(body: TestRunRequest):
    try:
        archive_bytes = base64.b64decode(body.archive_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "Invalid base64 repository snapshot") from exc
    if not archive_bytes or len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, "Repository snapshot is empty or too large")
    try:
        import docker
        from docker.errors import DockerException, ImageNotFound
        client = docker.from_env(timeout=body.timeout_seconds + 20)
        client.ping()
        client.images.get(RUNNER_IMAGE)
    except ImportError as exc:
        raise HTTPException(503, "Docker SDK is not installed in the sandbox controller") from exc
    except ImageNotFound as exc:
        raise HTTPException(503, "Sandbox runner image is not built; build the sandbox image first") from exc
    except DockerException as exc:
        raise HTTPException(503, "Isolated container runtime is unavailable") from exc

    if not JOB_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Sandbox is at its concurrent test-run limit; retry shortly")
    started = time.monotonic()
    container = None
    timer = None
    timed_out = False
    output = b""
    exit_code = None
    try:
        # Validate/extract locally, then copy into a per-job tmpfs mount. No host
        # paths or persistent volumes are exposed to the untrusted test process.
        with tempfile.TemporaryDirectory(prefix="repopilot-job-") as workspace:
            file_count = _extract_validated(archive_bytes, workspace)
            if file_count == 0:
                raise HTTPException(400, "Repository snapshot contains no files")
            normalized = io.BytesIO()
            with tarfile.open(fileobj=normalized, mode="w") as outgoing:
                for root, dirs, filenames in os.walk(workspace, followlinks=False):
                    dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
                    for filename in filenames:
                        path = os.path.join(root, filename)
                        if os.path.islink(path):
                            continue
                        outgoing.add(path, arcname=os.path.relpath(path, workspace), recursive=False)
            container = client.containers.create(
                RUNNER_IMAGE,
                command=["sleep", str(body.timeout_seconds + 15)],
                working_dir="/workspace",
                network_mode="none",
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m",
                       "/workspace": "rw,noexec,nosuid,size=128m"},
                mem_limit="512m",
                memswap_limit="512m",
                nano_cpus=1_000_000_000,
                pids_limit=64,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="10001:10001",
                environment={"PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                labels={"com.repopilot.sandbox": "true"},
            )
            container.start()
            if not container.put_archive("/workspace", normalized.getvalue()):
                raise HTTPException(503, "Could not stage repository snapshot in sandbox")

            def stop_at_deadline():
                try:
                    container.kill()
                except DockerException:
                    pass

            timer = threading.Timer(body.timeout_seconds, stop_at_deadline)
            timer.daemon = True
            timer.start()
            try:
                result = container.exec_run(
                    ["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    workdir="/workspace",
                    environment={"PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                    demux=False,
                    stdout=True,
                    stderr=True,
                )
                exit_code = result.exit_code
                output = result.output or b""
                if time.monotonic() - started >= body.timeout_seconds:
                    timed_out = True
            except DockerException:
                timed_out = True
                output = b"Test process exceeded its execution deadline and was terminated."
            finally:
                timer.cancel()
                timer = None
                try:
                    container.kill()
                except DockerException:
                    pass
        if isinstance(output, tuple):
            output = b"\n".join(part for part in output if part)
        if isinstance(output, str):
            output = output.encode("utf-8", "replace")
        return TestRunResponse(
            status="timed_out" if timed_out else ("passed" if exit_code == 0 else "failed"),
            exit_code=exit_code,
            output=output.decode("utf-8", "replace")[-30000:],
            duration_seconds=round(time.monotonic() - started, 3),
            timed_out=timed_out,
        )
    except DockerException as exc:
        raise HTTPException(503, "Sandbox container could not be started") from exc
    finally:
        if timer is not None:
            timer.cancel()
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        JOB_SLOTS.release()

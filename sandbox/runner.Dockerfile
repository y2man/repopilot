# Prebuilt, dependency-light test image. Repository code is mounted read-only and
# never installed into this image. Add only trusted baseline test tooling here.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir pytest==8.3.5
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT []

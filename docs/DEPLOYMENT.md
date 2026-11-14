# Deployment checklist

## 1. Prepare the host

Install Docker Engine and the Docker Compose plugin. Point DNS for your domain at the host. Put a TLS reverse proxy (Caddy, Traefik, or managed load balancer) in front of the Compose `web` service on port 80. Do not publish PostgreSQL, Redis, or the API port directly to the public internet.

## 2. Configure secrets

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `SECRET_KEY`. Generate a different strong random `POSTGRES_PASSWORD`. Set:

- `APP_ENV=production`
- `GROQ_API_KEY` and the desired `GROQ_MODEL`
- `FRONTEND_URL=https://your-domain.example`
- `PUBLIC_API_URL=https://your-domain.example`
- `CORS_ORIGINS=["https://your-domain.example"]`
- `ALLOWED_HOSTS=["your-domain.example"]`

For semantic retrieval, keep `INSTALL_LOCAL_EMBEDDINGS=true`. This downloads model dependencies and weights during the image build. Set `RERANKER_ENABLED=true` only if the host has enough memory/CPU for the additional CrossEncoder model.

## 3. Optional GitHub OAuth

Create a GitHub OAuth App with:

- Homepage URL: `https://your-domain.example`
- Authorization callback URL: `https://your-domain.example/api/v1/auth/github/callback`

Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in `.env`. The app stores the resulting user token encrypted at rest. Users link GitHub from the Repositories screen. A shared `GITHUB_TOKEN` fallback is supported for a single-operator instance but is not preferred for multi-user deployments.

## 4. Build and start

```bash
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs -f api worker
```

The API container runs Alembic migrations before starting. It refuses production startup if the secret/database configuration is unsafe, if the schema is not at Alembic head, or if Redis is unavailable. The worker consumes Celery re-index jobs.

## 5. Verify

- Visit `https://your-domain.example/health` and confirm `status=ok`, `database=ok`, and `redis=ok`.
- Open `/docs` and verify the API schema loads.
- Register a user, upload a small test ZIP, open Code Explorer, and ask a question.
- Link a test GitHub account, import a repository, create a patch proposal, approve it, and publish only after reviewing the diff.
- Check `docker compose logs api worker` for migration and worker startup errors.

## 6. Backups and operations

Back up PostgreSQL regularly and test restores. Preserve the `.env` secret securely: GitHub OAuth tokens are encrypted with `SECRET_KEY`, so losing/rotating it requires users to reconnect GitHub. Configure log collection, uptime monitoring, alerts, and a database retention policy. Do not commit `.env`.

## 7. Known acceptance limitation

This delivery does not include an arbitrary command/test execution sandbox. Do not run untrusted repository code on the API host or Celery worker. A separate isolated runner is required before enabling test/command execution. Also run the frontend build and Compose smoke test in a Docker/npm-enabled environment; those could not be executed in the development workspace used to prepare this archive.

## Isolated Python test runner

The test-runner control service is separate from the API and Celery worker. The root Compose file places the same-host sandbox behind the opt-in `local-sandbox` profile for local development only. Production should deploy the controller on a dedicated disposable Linux VM using `sandbox/compose.yml`, then set the API `SANDBOX_URL` to the controller private address. It creates a fresh, disposable container for each test request. The test container has no network, a read-only repository snapshot, a read-only root filesystem, a small writable `/tmp`, no Linux capabilities, `no-new-privileges`, a non-root UID, a 512 MiB memory cap, one CPU, a 64-process cap, and a hard execution timeout. Only the fixed `python -B -m pytest -q` command is exposed; callers cannot submit shell commands, Docker options, image names, or arbitrary arguments. The runner validates archive paths and sizes before creating the container.

Configure a unique `SANDBOX_SHARED_SECRET` on both the API and controller (do not reuse `SECRET_KEY`). On the dedicated runner VM, copy `sandbox/.env.example` to `sandbox/.env`, set the same shared secret, set `DOCKER_GID` to the group ID owning `/var/run/docker.sock` (`stat -c %g /var/run/docker.sock`), and set `SANDBOX_BIND_ADDRESS` to its private interface address. Start the separate stack:

```bash
cd sandbox
cp .env.example .env
docker compose --profile build build sandbox-image
docker compose up -d --build sandbox
```

Restrict TCP/8090 to the application host or VPN subnet using host/cloud firewall rules. Set `SANDBOX_URL=http://PRIVATE_RUNNER_IP:8090` in the application environment and deploy the API normally without the `local-sandbox` profile. For local development on one machine only, the root Compose file supports `docker compose --profile sandbox-build build sandbox-image` followed by `docker compose --profile local-sandbox up --build -d`.

Authenticated users can run the indexed repository's Python tests with `POST /api/v1/tests/run` and JSON `{"repository_id": 123, "timeout_seconds": 45}`. The response and agent execution history record the test output. The endpoint runs tests against the indexed snapshot, not a live checkout. Only pytest itself is preinstalled; project-specific dependencies are intentionally not installed from untrusted repository manifests. Tests that require undeclared third-party packages will report import errors until a future reviewed dependency-image workflow is configured.

**Critical Docker trust boundary:** the sandbox controller needs access to the Docker daemon socket to create disposable containers. Docker socket access is effectively host-root authority. Do not deploy the controller on a shared application host or expose its HTTP port publicly. For production, place it on a dedicated disposable Linux VM/worker with no production secrets, restrict network access to the API-to-runner path, rotate its shared secret, and treat the VM as disposable. Do not mount the Docker socket into the API or Celery worker. The production sandbox Compose file binds only to the configured private interface; Compose networking is not a substitute for host-level firewall policy. The runner image must be rebuilt and scanned as part of routine maintenance.


## GitHub push synchronization

Set `GITHUB_WEBHOOK_SECRET` in the API environment. In the GitHub repository settings, add a webhook pointing to `https://YOUR_DOMAIN/api/v1/webhooks/github`, choose `application/json`, configure the exact same secret, and subscribe to the `push` event. The handler validates `X-Hub-Signature-256`, records `X-GitHub-Delivery` for idempotency, and queues a Celery task only when the pushed branch matches the linked repository's tracked ref. The worker downloads the archive from the fixed GitHub API host using the linked user's encrypted OAuth token where available, safely replaces the indexed snapshot, and records delivery status. Confirm Redis and the Celery worker are healthy before enabling the webhook. Re-deliveries of a completed or queued delivery do not enqueue duplicate sync jobs.

## Audit retention and request tracing

Authentication, patch approval/rejection/rollback/publishing, sandbox test runs, repository deletion, and GitHub webhook synchronization write owner-scoped audit events. `GET /api/v1/audit` exposes only the authenticated user's events. HTTP access logs are JSON-formatted and include a validated/generated `X-Request-ID`, method, path, status, and duration; request bodies, query strings, authorization headers, and secrets are not logged. Forward the request ID into your log aggregator and include it when reporting an incident.

Set `AUDIT_RETENTION_DAYS` (default 365; cleanup clamps to 30–3650 days). Schedule the cleanup script with your host scheduler, for example weekly:

```bash
cd backend
python scripts/prune_audit_events.py
```

Configure PostgreSQL backups and point-in-time recovery with your database provider. Before production releases, rehearse restore into a separate database and verify the latest Alembic head. The application does not create or validate your cloud backup policy automatically.


## Database backups and restore

The Compose helpers `infra/backup-postgres.sh` and `infra/restore-postgres.sh` use the database container's `pg_dump`/`pg_restore` binaries and custom-format archives. The backup script writes mode-0600 dump and SHA-256 sidecar files under `./backups/` by default. Schedule it regularly, copy backups to encrypted off-host/object storage, and apply a retention policy. Restore requires both `CONFIRM_RESTORE=YES` and `BACKUP_FILE=...`; it verifies the checksum when a sidecar exists, stops API/worker writes, restores, and restarts them. Run restore drills in a separate staging environment first. These scripts do not provision cloud storage or create a backup schedule themselves.

The starter retrieval benchmark is in `backend/evaluation/data/retrieval_golden.json`; run `python scripts/evaluate_retrieval.py` from `backend/`. It is a smoke benchmark over a small synthetic corpus, not a validated production quality gate. Add expert-reviewed queries and expected source paths from representative real repositories before setting release thresholds.


## Prometheus metrics

The API exposes Prometheus text-format HTTP request counters and duration histograms at `/metrics`. The endpoint is not proxied by the public Nginx frontend and the API service port is not published by Compose; scrape it from a private monitoring container/network. Labels use the matched FastAPI route template rather than concrete repository IDs to avoid unbounded cardinality. Connect your own Prometheus/alertmanager or managed monitoring service and define SLO alerts; no monitoring server is bundled in this stack.

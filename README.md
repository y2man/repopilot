# RepoPilot

RepoPilot is an AI-powered repository intelligence workspace. It combines a React/TypeScript glassmorphism frontend, FastAPI, PostgreSQL + pgvector, Redis/Celery, Tree-sitter parsing, Sentence Transformers embeddings, and Groq-backed evidence-grounded analysis.

## Current implemented capabilities

- Email/password registration and login, PBKDF2 password hashing, signed expiring JWTs, and per-user repository authorization.
- GitHub OAuth linking. User access tokens are encrypted at rest using a key derived from `SECRET_KEY`; tokens are never returned to the browser. Public GitHub repository import works without OAuth; private imports use the connected user's token.
- ZIP upload with upload-size limits, ZIP validation, traversal/symlink/secret/dependency/binary filtering, expansion limits, duplicate path filtering, and text file size limits.
- GitHub repository archive import using the fixed GitHub API host. The default branch/ref is recorded for later publishing. Signed GitHub push webhooks are verified and deduplicated before Celery synchronization of the tracked branch.
- Language identification, Python AST symbol extraction, Tree-sitter symbol extraction for supported languages, line-aware chunking, and repository symbol lookup.
- Optional `all-MiniLM-L6-v2` embeddings, pgvector HNSW indexing, lexical retrieval, reciprocal-rank hybrid fusion, optional CrossEncoder reranking, metadata filtering, and bounded context construction.
- Groq chat with evidence-only instructions, file/line citations, actual token streaming over SSE, and persisted conversation/message history.
- Bounded repository investigation tools: search indexed code, find symbols, read a specific repository file range, and inspect imports. Tool execution is allowlisted and capped; repository code is never executed by the agent.
- Evidence-based code review and debugging investigations. These are AI analyses of retrieved source; they do not claim that external scanners or tests ran.
- AI patch proposals, diff preview, explicit human approval/rejection, stale-source conflict checks, snapshot re-indexing, ZIP export, explicit GitHub publishing, and conflict-checked rollback commits for published changes.
- AI-generated test-file proposals that remain pending until human approval.
- Celery/Redis background re-index jobs with persisted status/progress.
- Redis-backed production rate limiting for authentication, upload/import, chat, review, agent investigation, and sandbox test runs; production host validation, security headers, structured request-ID logging, Prometheus-format request metrics at the private `/metrics` endpoint, and owner-scoped audit history.
- Alembic migrations, Docker Compose services, non-root backend container, API health checks, and Nginx reverse proxy configuration.
- Offline retrieval evaluation metrics plus a curated eight-query smoke benchmark.
- Owner-scoped audit history, structured request-ID access logs, audit-retention cleanup, and PostgreSQL custom-format backup/restore scripts.

## Quick start

1. Copy `.env.example` to `.env`.
2. Replace every `YOUR_DOMAIN` and `replace-with-*` value. Set a random `SECRET_KEY` (at least 32 characters) and a strong `POSTGRES_PASSWORD`.
3. Add `GROQ_API_KEY` to enable AI chat, review, debugging, patch generation, and agent planning.
4. Create a GitHub OAuth App if you want private repository access and GitHub publishing:
   - Homepage URL: `https://YOUR_DOMAIN`
   - Authorization callback URL: `https://YOUR_DOMAIN/api/v1/auth/github/callback`
   - Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.
   - Set `FRONTEND_URL` and `PUBLIC_API_URL` to the public HTTPS origin.
   - Set `CORS_ORIGINS` and `ALLOWED_HOSTS` to your actual domain.
5. Generate a separate sandbox secret and set `SANDBOX_SHARED_SECRET` in `.env`. On Linux, set `DOCKER_GID` to `stat -c %g /var/run/docker.sock`. The sandbox controller requires Docker socket access; for production, place it on a dedicated disposable VM, not the application host.
6. For local development only, build the fixed test-runner image and enable the local sandbox profile:

   ```bash
   docker compose --profile sandbox-build build sandbox-image
   docker compose --profile local-sandbox up --build -d
   ```

   For production, do not enable `local-sandbox` on the application host. Deploy the sandbox controller on a dedicated disposable Linux VM using `sandbox/compose.yml`, restrict its port to a private network, and set `SANDBOX_URL` in the application `.env` to that private endpoint.

7. Open `https://YOUR_DOMAIN` (or `http://localhost` for a local Compose run). API docs are proxied at `/docs`; health is `/health`.

The Compose stack contains PostgreSQL/pgvector, Redis, FastAPI, a Celery worker, and the Nginx-served frontend. Database and Redis ports are not published to the host by default. Put TLS in front of the web service for production.

## Environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | JWT signing and encryption key for stored GitHub OAuth tokens |
| `DATABASE_URL` | SQLAlchemy PostgreSQL URL; Neon `postgresql://` URLs are normalized to psycopg |
| `REDIS_URL` | Redis connection used for production rate limiting and Celery jobs |
| `POSTGRES_PASSWORD` | PostgreSQL password used by Compose |
| `GROQ_API_KEY` | Groq API credential; required for AI generation |
| `GROQ_MODEL` | Groq chat model, defaults to `openai/gpt-oss-120b` |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | Optional per-user GitHub OAuth integration |
| `GITHUB_WEBHOOK_SECRET` | Optional GitHub webhook signing secret for push-based synchronization |
| `GITHUB_TOKEN` | Optional shared PAT fallback for a single-operator deployment; OAuth is preferred |
| `FRONTEND_URL` | Public frontend origin used after OAuth callback |
| `PUBLIC_API_URL` | Public API origin used as GitHub OAuth callback base |
| `VITE_API_URL` | Public backend origin compiled into the Vercel frontend; never a secret |
| `CORS_ORIGINS` | JSON array of allowed browser origins |
| `ALLOWED_HOSTS` | JSON array of accepted Host header names |
| `INSTALL_LOCAL_EMBEDDINGS` | Build-time toggle; when true, installs Sentence Transformers and preloads MiniLM weights |
| `RERANKER_ENABLED` | Enables optional CrossEncoder reranking (also preloads model at build time) |
| `MAX_UPLOAD_MB` | ZIP/GitHub archive size cap |
| `AUDIT_RETENTION_DAYS` | Audit history retention; scheduled prune script clamps to 30–3650 days |
| `SANDBOX_SHARED_SECRET` | Separate shared secret between API and private sandbox controller |
| `SANDBOX_URL` | Private URL of the sandbox controller; production should point to its dedicated VM |
| `DOCKER_GID` | Linux Docker socket group ID for the sandbox controller |

`INSTALL_LOCAL_EMBEDDINGS=true` is the full RAG default. It makes the backend image substantially larger and requires access to the model registry during image build. Set it to `false` for a smaller lexical-only installation. `RERANKER_ENABLED=true` adds another model download and more CPU/memory use.

## Deploying with Neon, Render, and Vercel

Create credentials in your own provider accounts; do not commit them or put server secrets in Vercel. The frontend only needs the public API URL.

1. **Neon PostgreSQL** — create a project at [Neon Console](https://console.neon.tech/), copy its connection string, and set it as `DATABASE_URL` in Render. The backend accepts Neon’s `postgresql://` URL and selects the installed psycopg driver. Migrations enable the `vector` extension used by pgvector.
2. **Groq** — create an API key at [Groq Console](https://console.groq.com/keys/) and set `GROQ_API_KEY` on the Render backend only. Keep `GROQ_MODEL` at the configured default unless you choose another model available to your account.
3. **Render backend** — create a Docker web service from this repository using `backend` as the root directory and `/health` as its health-check path. Set `APP_ENV=production`, `SECRET_KEY` (generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`), `DATABASE_URL`, `GROQ_API_KEY`, and `REDIS_URL`. Production also needs a Render Key Value instance for Redis and a background worker using `celery -A app.core.celery_app.celery_app worker --loglevel=INFO --concurrency=2`; add the same database, Redis, Groq, `APP_ENV`, and `SECRET_KEY` values to the worker. Render services may incur charges; review the plan before creating them.
4. **Vercel frontend** — import the repository at [Vercel](https://vercel.com/dashboard), set the project root to `frontend`, and add `VITE_API_URL` with the Render backend’s public origin (for example, `https://your-api.onrender.com`, without a trailing slash). Set this variable for the production deployment and redeploy after changing it.
5. **Connect the domains** — after Vercel gives you the frontend URL, set these on Render: `FRONTEND_URL` to that origin, `PUBLIC_API_URL` to the Render API origin, `CORS_ORIGINS` to a JSON array containing the exact frontend origin, and `ALLOWED_HOSTS` to a JSON array containing the Render hostname (host only, no scheme).
6. **Optional GitHub OAuth** — create an OAuth App at [GitHub Developer Settings](https://github.com/settings/developers). Use the Vercel URL as its homepage and `https://YOUR-RENDER-HOST/api/v1/auth/github/callback` as its callback URL; set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` on Render. The app already supports email/password registration and login; GitHub OAuth links repository access to a signed-in account.

The app's `/health` response reports database, Redis, Groq, and GitHub OAuth configuration status. A live provider test requires you to set the credentials in the corresponding dashboards; never send API keys, database URLs, OAuth secrets, or `SECRET_KEY` in chat.

## Local development

Backend:

```bash
cd backend
python -m venv .venv
# activate the virtual environment
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` and `/health` to `http://localhost:8000`. Local development defaults to SQLite. Set `DATABASE_URL` to PostgreSQL to exercise pgvector.

Celery worker (requires Redis and the backend dependencies):

```bash
cd backend
celery -A app.core.celery_app.celery_app worker --loglevel=INFO
```

## API overview

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `POST /api/v1/webhooks/github` (public GitHub push webhook; HMAC signature required)
- `GET /api/v1/audit` (owner-scoped security and workflow event history)
- `GET /api/v1/auth/github/start`, `GET /api/v1/auth/github/callback`, `GET /api/v1/auth/github/status`, `DELETE /api/v1/auth/github`
- `POST /api/v1/repositories/upload`, `POST /api/v1/repositories/github`
- `GET/DELETE /api/v1/repositories/{id}`
- `GET /api/v1/repositories/{id}/files`, `GET /api/v1/repositories/{id}/files/content`
- `GET /api/v1/repositories/{id}/symbols`, `GET /api/v1/repositories/{id}/search`
- `POST /api/v1/repositories/{id}/reindex`, `GET /api/v1/repositories/{id}/jobs`
- `GET /api/v1/repositories/{id}/export`
- `POST /api/v1/chat`, `POST /api/v1/chat/stream`
- `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}/messages`
- `POST /api/v1/agent/investigate`, `GET /api/v1/agent/executions`
- `POST /api/v1/review`
- `POST /api/v1/patches/propose`, `POST /api/v1/tests/generate`, `POST /api/v1/tests/run` (isolated Python pytest)
- `POST /api/v1/patches/{id}/approve`, `/reject`, `/publish`, `/rollback`, `/revert-github`

Except health/docs, the GitHub OAuth callback, and the HMAC-signed GitHub webhook, application API routes require `Authorization: Bearer <token>`. Repository and conversation ownership is checked on access.

## Important execution boundary

**Arbitrary shell commands and repository-controlled install/build steps are intentionally not enabled.** The agent is read-only; it does not execute repository code on the API host. The only execution path is a fixed Python `pytest` invocation inside the isolated runner described below. Patch approval changes RepoPilot's stored repository snapshot; for GitHub repositories, publishing is a separate explicit commit action. ZIP repositories can be exported after changes.

An isolated Python test-runner controller is included separately from the API and Celery worker. It creates disposable containers with no network, a read-only root filesystem, bounded tmpfs, non-root UID, dropped capabilities, no-new-privileges, CPU/memory/PID/time limits, and only a fixed pytest command. Tests run against the indexed snapshot and results are persisted. Project-specific dependencies are not installed from untrusted manifests. The controller requires Docker socket access, which is effectively host-root authority: deploy it only on a dedicated disposable Linux VM, never on a shared production application host. The sandbox still requires real Docker execution and an independent security audit before production use.

## Tests and verification

Backend tests:

```bash
cd backend
pytest -q
cd ../
PYTHONPATH=sandbox pytest -q sandbox/tests
cd frontend
npm test
npx playwright install chromium
npm run test:e2e
```

Migrations (run from `backend`):

```bash
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

Retrieval smoke benchmark (run from `backend`):

```bash
python scripts/evaluate_retrieval.py
```

PostgreSQL backup/restore scripts (run from the project root with the Compose stack available):

```bash
infra/backup-postgres.sh
CONFIRM_RESTORE=YES BACKUP_FILE=./backups/repopilot-YYYYMMDDTHHMMSSZ.dump infra/restore-postgres.sh
```

The backend test suite covers authentication, owner isolation, ZIP security, source line preservation, Python symbol extraction, retrieval, context budgets, persistent chat, streaming behavior, investigation persistence, patch approval/conflict/rollback behavior, generated test approval, sandbox request/authentication and execution-history persistence, GitHub webhook signature/idempotency/branch filtering, audit ownership, GitHub URL validation, credential encryption, and ZIP export. The separate sandbox test suite covers traversal/symlink rejection, authentication, and the fixed hardened container configuration using a mocked Docker daemon; it does not replace a real Docker execution test.

## Production operations

- Use a managed PostgreSQL database with pgvector, backups, and point-in-time recovery.
- Keep PostgreSQL and Redis private; only expose the web/reverse-proxy service.
- Configure TLS, domain DNS, `ALLOWED_HOSTS`, and `CORS_ORIGINS`.
- Rotate `SECRET_KEY` only with a plan to reconnect GitHub OAuth (stored OAuth tokens are encrypted using this key).
- Configure log aggregation and alerting; request logs carry `X-Request-ID`. Schedule `backend/scripts/prune_audit_events.py` according to your audit-retention policy. Schedule `infra/backup-postgres.sh`, copy backups off-host, and rehearse `infra/restore-postgres.sh` into a staging database.
- Use a managed secret store rather than committing `.env`. Scrape `/metrics` from a private monitoring network; the Nginx public proxy intentionally does not expose it.
- Build images with dependency/model registries reachable. The current development environment used for this package could not reach npm/PyPI registries and did not have Docker, so a Docker Compose deployment and real frontend production bundle could not be executed here.

## Project structure

```text
RepoPilot/
├── frontend/       # React, TypeScript, Vite, Tailwind, Motion, Nginx
├── backend/
│   ├── app/api/    # Auth, repository, chat, workflow endpoints
│   ├── app/ai/     # Bounded agent tools
│   ├── app/core/   # Config, DB, auth, Celery
│   ├── app/ingestion/ # ZIP ingestion, AST/Tree-sitter parsing
│   ├── app/rag/    # Hybrid retrieval and context building
│   ├── app/services/ # Embeddings and Groq provider
│   ├── app/tasks.py # Background indexing
│   ├── alembic/    # Database migrations
│   └── tests/      # Backend unit and API tests
├── infra/          # PostgreSQL initialization and backup/restore scripts
├── sandbox/        # Isolated test controller and fixed runner image
├── docs/           # Architecture, deployment and roadmap
└── docker-compose.yml
```

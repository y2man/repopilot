# RepoPilot implementation and acceptance roadmap

## Implemented in this delivery
- [x] React/TypeScript glassmorphism workspace with ambient lighting, animated interactions, responsive navigation, reduced-motion support, account screen, repositories, streaming chat, code explorer, search, review, debugging, agent activity, patch preview, and settings.
- [x] FastAPI service with health/readiness reporting, OpenAPI docs, startup schema validation, and production security headers.
- [x] Registration/login, PBKDF2 password hashing, signed expiring JWTs, per-user repository authorization, Redis-backed production rate limits, and host validation.
- [x] GitHub OAuth link/unlink with encrypted per-user tokens, public/private archive import, signed/idempotent push webhooks with Celery background synchronization, and explicit GitHub commit publishing for approved patches.
- [x] ZIP ingestion with upload limits, traversal/symlink rejection, file-count/expanded-size limits, secret/dependency/binary filtering, and no host extraction.
- [x] Language metadata, Python AST symbols, Tree-sitter symbol extraction for supported languages, line-aware chunks, and import inspection.
- [x] all-MiniLM-L6-v2 embeddings, pgvector support, lexical retrieval, reciprocal-rank hybrid fusion, optional CrossEncoder reranking, metadata filters, bounded context construction, and offline retrieval metrics.
- [x] Groq chat with SSE token streaming, persistent conversations/messages, evidence-grounded answers, source citations, and no fabricated answers when provider/evidence is unavailable.
- [x] Bounded AI-planned/read-only investigation tools with execution records; repository code is not run by the agent.
- [x] Evidence-based review/debugging, AI patch proposals, diff preview, explicit approve/reject, stale-source checks, generated test-file proposals, snapshot updates, ZIP export, and optional GitHub publishing.
- [x] Redis/Celery background re-indexing with persisted job status/progress.
- [x] Separate authenticated sandbox controller and disposable Python test containers: no network, read-only root filesystem, bounded tmpfs workspace, non-root UID, dropped capabilities, no-new-privileges, CPU/memory/PID/time limits, fixed pytest command, per-process concurrency cap, and persisted results.
- [x] Frontend action to run the indexed Python test snapshot and inspect sandbox output.
- [x] Snapshot rollback for approved patches and conflict-checked GitHub revert commits (restoring original file content or deleting newly added files).
- [x] Owner-scoped audit history for authentication, patch changes, sandbox runs, repository deletion, and GitHub sync; structured request-ID logs, private Prometheus request metrics, and configurable audit retention cleanup.
- [x] Curated eight-query retrieval smoke benchmark and repeatable JSON metrics report; Postgres custom-format backup/restore scripts with checksum and explicit restore confirmation.
- [x] SQLAlchemy models and eight Alembic schema migrations, PostgreSQL/pgvector + Redis + worker Compose services, non-root backend image, and Nginx frontend proxy.
- [x] Backend unit/integration/security/workflow tests.

## Remaining before claiming full production acceptance
1. [ ] Independently security-audit and run the new sandbox on a dedicated disposable Linux VM. Docker socket access is host-root authority and the controller must not share a production host. Project-specific dependency installation and non-Python test runners remain disabled by design.
2. [ ] Expand frontend component and browser E2E coverage to repository/chat workflows and run the current unit/component/E2E suites with installed dependencies and browser binaries.
3. [ ] Real Docker Compose/PostgreSQL/pgvector/Redis/Celery/sandbox deployment verification in a Docker-enabled environment.
4. [ ] Expand the starter retrieval benchmark with reviewed real-world repositories and add answer groundedness/faithfulness thresholds.
5. [ ] Connect the private Prometheus metrics endpoint to alerting and perform actual backup/restore drills in a deployed environment.

## Verification performed in the available workspace
- Backend tests: 37 passed (including sandbox API boundary, webhook signature/idempotency, and patch rollback tests).
- Sandbox-controller tests: 7 passed (archive traversal, symlink rejection, auth checks, and mocked enforcement of container isolation settings).
- GitHub webhook tests: included in backend suite (signature validation, tracked-branch filtering, and idempotent queueing).
- Alembic migration chain: fresh upgrade to 0008, downgrade to base, and re-upgrade passed on SQLite.
- Python compilation: passed.
- Python package wheel build: passed using installed build tooling (`--no-build-isolation`).
- Docker Compose YAML parsing and sandbox dependency/socket configuration checks: passed.
- Frontend TSX syntax parsing: passed. Vitest and Playwright unit/E2E test suites were added but cannot be executed until npm dependencies and browser binaries are installed.

## Verification blocked by this environment
- `npm install` could not reach `registry.npmjs.org` (`EAI_AGAIN`), so actual frontend dependency resolution and `vite build` remain unverified.
- Docker is not installed, so images, PostgreSQL/pgvector, Redis, Celery worker startup, actual sandbox execution, and end-to-end Compose behavior remain unverified.
- No live Groq key, GitHub OAuth app, webhook registration, or deployment credentials were supplied; external integrations have not been live-tested.

Run the remaining checks in an environment with npm registry access and Docker:

```bash
cd frontend && npm install && npm run build
cd ../backend && pytest -q
cd .. && docker compose config && docker compose up --build
```

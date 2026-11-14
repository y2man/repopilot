# RepoPilot architecture

```text
React + TypeScript + Vite + Tailwind + Motion
        | Bearer-authenticated JSON / multipart / SSE
        v
Nginx reverse proxy
        v
FastAPI routers
  |-- auth: registration/login + GitHub OAuth link/unlink
  |-- repositories: ZIP/GitHub import, files, symbols, export, re-index jobs
  |-- chat: persisted conversations, hybrid retrieval, Groq SSE
  |-- workflows: bounded investigation, review, debugging, patch/test proposals, rollback
  |-- webhooks: signed/idempotent GitHub push intake
  |-- audit: owner-scoped security and workflow history
        |
        +--> Redis --> Celery worker --> re-indexing and GitHub sync tasks
        +--> private sandbox controller --> disposable network-disabled test containers
        |
        v
Service layer
  |-- ZIP safety, filtering, and line-aware chunking
  |-- Python AST + Tree-sitter symbol extraction
  |-- Sentence Transformers 384-dim embeddings
  |-- pgvector + lexical RRF hybrid retrieval + optional CrossEncoder
  |-- bounded context construction and Groq completion/streaming
        |
        v
SQLAlchemy -> PostgreSQL + pgvector
              SQLite for local development
```

## Trust boundaries

- The browser holds an expiring bearer token in `sessionStorage`; Groq and GitHub credentials stay on the backend.
- GitHub OAuth tokens are encrypted at rest using a key derived from `SECRET_KEY`. Rotating that secret requires reconnecting GitHub.
- Every repository, conversation, agent run, and patch operation is scoped to the authenticated owner.
- ZIP entries are read in memory and are never extracted to an application path. Traversal paths, symlinks, known secrets, dependency folders, binaries, and oversized files are excluded.
- Repository source is passed to the LLM as untrusted evidence. Agent tools are allowlisted and bounded; they search/read/inspect only and do not execute repository code.
- Patch proposals are stored as pending until human approval. Applying updates the RepoPilot repository snapshot; local rollback checks for concurrent edits. GitHub publishing is a separate explicit commit operation with remote-content conflict checks, and a published patch can be reverted by a new commit only when the remote file still exactly matches the proposal.
- Security-sensitive workflow actions are written to an owner-scoped audit table; request logs use generated/validated request IDs and omit request bodies and query strings. The API exposes Prometheus-format request counters and latency histograms on an internal-only `/metrics` endpoint.
- GitHub webhook requests are HMAC-verified and delivery IDs are persisted for idempotency; only the tracked branch is queued for synchronization.
- The API packages the indexed snapshot and sends it to a separate authenticated sandbox controller. The controller starts a disposable container with network disabled, a read-only root filesystem, bounded tmpfs workspace, non-root UID, dropped capabilities, no-new-privileges, and CPU/memory/PID/time limits. Only a fixed pytest invocation is allowed. The controller has Docker socket access (host-root authority), so production deployment requires a dedicated disposable Linux VM and an independent security audit. No arbitrary shell command interface exists.

## Retrieval behavior

Chunks preserve repository ID, path, language, and inclusive start/end line numbers. `all-MiniLM-L6-v2` creates normalized 384-dimensional embeddings stored in pgvector. Lexical and vector result rankings are combined with reciprocal-rank fusion; an optional CrossEncoder reranker can be enabled at build/deploy time. If the embedding package/model is unavailable, retrieval falls back to lexical ranking and does not claim semantic search. Context construction uses a conservative character/token budget and preserves source location headers.

## Background work

ZIP and GitHub imports currently index synchronously. Explicit re-index requests are persisted as `IndexingJob` records and sent through Redis/Celery. The worker rebuilds symbols/chunks/embeddings and updates real progress/status fields. The API never fabricates indexing progress.

## Deployment model

Docker Compose keeps PostgreSQL and Redis private to the Compose network. Nginx exposes the frontend and proxies API/docs/health routes. The API runs non-root, validates production secrets and migration head, applies Redis-backed request limits, and validates allowed hosts. TLS termination, managed secrets, backups, monitoring, and restore drills belong at the deployment edge/operations layer.

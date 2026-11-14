#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "Refusing restore. Set CONFIRM_RESTORE=YES and BACKUP_FILE=/path/to/repopilot.dump." >&2
  exit 2
fi
if [[ -z "${BACKUP_FILE:-}" || ! -f "$BACKUP_FILE" ]]; then
  echo "BACKUP_FILE must point to an existing custom-format pg_dump file." >&2
  exit 2
fi
if [[ -f "${BACKUP_FILE}.sha256" ]]; then
  (cd "$(dirname "$BACKUP_FILE")" && sha256sum --check "$(basename "$BACKUP_FILE").sha256")
fi

restart_services() {
  docker compose start api worker >/dev/null 2>&1 || true
}
trap restart_services EXIT

echo "Stopping API and worker to prevent writes during restore..."
docker compose stop api worker

echo "Restoring PostgreSQL database from $BACKUP_FILE ..."
docker compose exec -T db sh -lc 'pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$BACKUP_FILE"

echo "Starting API and worker..."
docker compose start api worker
trap - EXIT
echo "Restore completed. Verify /health, Alembic head, and application workflows before reopening traffic."

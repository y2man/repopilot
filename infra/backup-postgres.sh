#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="${BACKUP_DIR%/}/repopilot-${STAMP}.dump"
mkdir -p "$BACKUP_DIR"
umask 077

docker compose exec -T db sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' > "$FILE"
sha256sum "$FILE" > "${FILE}.sha256"
chmod 600 "$FILE" "${FILE}.sha256"
printf 'Backup created: %s\n' "$FILE"

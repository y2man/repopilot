"""Delete audit events older than AUDIT_RETENTION_DAYS; schedule via host cron."""
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import AuditEvent

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main() -> int:
    settings = get_settings()
    retention_days = max(30, min(settings.audit_retention_days, 3650))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with SessionLocal() as db:
        result = db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
        db.commit()
        count = result.rowcount or 0
    logging.info('{"event":"audit_retention_pruned","deleted":%s,"retention_days":%s}', count, retention_days)
    return count


if __name__ == "__main__":
    main()

"""Small, transaction-aware audit helper. Never pass secrets or raw request bodies."""
from app.models import AuditEvent


def record_audit(
    db,
    *,
    action: str,
    owner_id: int | None = None,
    repository_id: int | None = None,
    resource_type: str = "",
    resource_id: str | int = "",
    status: str = "success",
    details: dict | None = None,
) -> None:
    db.add(AuditEvent(
        owner_id=owner_id,
        repository_id=repository_id,
        action=action[:100],
        resource_type=resource_type[:64],
        resource_id=str(resource_id)[:128],
        status=status[:32],
        details=details or {},
    ))

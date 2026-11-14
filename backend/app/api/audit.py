from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.repositories import owned_repo
from app.core.database import get_db
from app.core.security import current_user
from app.models import AuditEvent, User

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
def list_audit_events(
    repository_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = select(AuditEvent).where(AuditEvent.owner_id == user.id)
    if repository_id is not None:
        owned_repo(db, repository_id, user.id)
        query = query.where(AuditEvent.repository_id == repository_id)
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)).all()
    return [{
        "id": row.id,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "repository_id": row.repository_id,
        "status": row.status,
        "details": row.details,
        "created_at": row.created_at,
    } for row in rows]

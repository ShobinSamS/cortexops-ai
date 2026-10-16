from datetime import datetime
from sqlalchemy import inspect
from fastapi import HTTPException

from app.models.entities import AuditLog


def serialize(row, exclude=()):
    result = {}
    for attr in inspect(row).mapper.column_attrs:
        if attr.key in exclude:
            continue
        value = getattr(row, attr.key)
        result[attr.key] = value.isoformat() if isinstance(value, datetime) else value
    return result


def audit(db, principal, action, resource_type, resource_id=None, detail=None):
    db.add(AuditLog(workspace_id=principal.workspace_id, user_id=principal.user_id, action=action,
                    resource_type=resource_type, resource_id=resource_id, detail=detail or {}))


async def owned(db, model, resource_id, principal, lock=False):
    from sqlalchemy import select
    statement = select(model).where(model.id == resource_id, model.workspace_id == principal.workspace_id)
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    if row is None:
        raise HTTPException(404, "Resource not found")
    return row

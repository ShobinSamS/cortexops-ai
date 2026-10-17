from datetime import timedelta

from sqlalchemy import select

from app.core.database import transaction
from app.core.security import Principal
from app.models.entities import Approval, User, WorkspaceMember, utcnow
from app.services.common import audit
from app.services.destinations import authorization_hash, write_target


async def request_approval(db, principal, server, tool, payload, investigation_id=None):
    target = write_target(principal.workspace_id, server, tool)
    item = Approval(workspace_id=principal.workspace_id, requested_by=principal.user_id, investigation_id=investigation_id,
                    server=server, tool=tool, payload=payload, target=target, payload_hash=authorization_hash(payload, target),
                    expires_at=utcnow() + timedelta(minutes=30))
    db.add(item)
    await db.flush()
    audit(db, principal, "approval.request", "approval", item.id, {"tool": tool})
    return item


async def execute_approval(approval_id):
    async with transaction() as db:
        approval = await db.scalar(select(Approval).where(Approval.id == approval_id).with_for_update())
        if approval is None or approval.status != "approved" or approval.consumed_at is not None or approval.expires_at <= utcnow():
            raise ValueError("Approval is no longer executable")
        user = await db.get(User, approval.decided_by)
        member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == approval.decided_by, WorkspaceMember.workspace_id == approval.workspace_id))
        if not user or not user.is_active or not member or member.role not in {"owner", "admin"}:
            raise ValueError("Approver no longer has administrator permission")
        p = Principal(user.id, member.workspace_id, member.role, user.email, user.name)
        approval.status = "executing"
        server, tool, payload, iid = approval.server, approval.tool, approval.payload, approval.investigation_id
    try:
        from app.mcp.client import invoke
        result = await invoke(server, tool, {**payload, "approval_id": approval_id}, p, iid)
        async with transaction() as db:
            approval = await db.get(Approval, approval_id)
            approval.status, approval.result = "executed", result
            audit(db, p, "approval.executed", "approval", approval_id, {"tool": tool})
        return result
    except Exception:
        async with transaction() as db:
            approval = await db.get(Approval, approval_id)
            approval.status = "failed"
            approval.result = {"error": "Approved operation failed; inspect tool history. If an external request timed out, verify its destination before requesting another approval."}
        raise

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, current_principal, require_role
from app.mcp import client
from app.mcp.tools import WRITE_TOOLS
from app.models.entities import MCPServer, ToolExecution, Approval, Investigation, utcnow
from app.schemas.contracts import ToolInvocation, ApprovalDecision
from app.services.auth import READ_TOOLS
from app.services.approvals import request_approval
from app.services.common import audit, owned, serialize
from app.services.jobs import enqueue

router = APIRouter()


class WritePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=1, max_length=8000)


class Permissions(BaseModel):
    allowed_tools: list[str] = Field(max_length=30)


@router.post("/mcp/servers/{server_id}/discover")
async def discover(server_id: str, p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db)):
    server = await owned(db, MCPServer, server_id, p)
    try:
        server.tools = await client.discover(server.kind, p)
        server.status = "connected"
    except Exception:
        server.status = "disconnected"
        server.last_checked_at = utcnow()
        await db.commit()
        raise HTTPException(503, "MCP connection failed; inspect the server log and startup command")
    server.last_checked_at = utcnow()
    audit(db, p, "mcp.discover", "mcp_server", server.id)
    return serialize(server)


@router.patch("/mcp/servers/{server_id}/permissions")
async def permissions(server_id: str, data: Permissions, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    server = await owned(db, MCPServer, server_id, p, lock=True)
    if any(tool not in READ_TOOLS[server.kind] for tool in data.allowed_tools):
        raise HTTPException(400, "Permission list includes an unknown tool")
    server.allowed_tools = sorted(set(data.allowed_tools))
    audit(db, p, "mcp.permissions", "mcp_server", server.id, {"allowed_tools": server.allowed_tools})
    return serialize(server)


@router.post("/mcp/tools/invoke")
async def invoke(data: ToolInvocation, p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db)):
    import json
    if len(json.dumps(data.arguments)) > 32000:
        raise HTTPException(400, "Tool arguments exceed the size limit")
    server = await db.scalar(select(MCPServer).where(MCPServer.workspace_id == p.workspace_id, MCPServer.kind == data.server))
    if server is None or data.tool not in server.allowed_tools:
        raise HTTPException(403, "Tool is not permitted for this workspace")
    if data.investigation_id:
        await owned(db, Investigation, data.investigation_id, p)
    if data.tool in WRITE_TOOLS:
        try:
            payload = WritePayload.model_validate(data.arguments).model_dump()
        except ValidationError:
            raise HTTPException(422, "Write arguments must contain a valid title and body, with no other fields")
        approval = await request_approval(db, p, data.server, data.tool, payload, data.investigation_id)
        return {"approval_required": True, "approval": serialize(approval)}
    try:
        return await client.invoke(data.server, data.tool, data.arguments, p, data.investigation_id)
    except Exception:
        raise HTTPException(503, "Tool invocation failed; inspect workspace tool history for the recorded error")


@router.get("/mcp/executions")
async def executions(investigation_id: str | None = None, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    statement = select(ToolExecution).where(ToolExecution.workspace_id == p.workspace_id)
    if investigation_id:
        await owned(db, Investigation, investigation_id, p)
        statement = statement.where(ToolExecution.investigation_id == investigation_id)
    return [serialize(x) for x in await db.scalars(statement.order_by(ToolExecution.created_at.desc()).limit(100))]


@router.get("/approvals")
async def approvals(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    return [serialize(x) for x in await db.scalars(select(Approval).where(Approval.workspace_id == p.workspace_id).order_by(Approval.created_at.desc()).limit(100))]


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, data: ApprovalDecision, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    approval = await owned(db, Approval, approval_id, p, lock=True)
    if approval.status != "pending" or approval.expires_at <= utcnow():
        raise HTTPException(409, "Approval expired or already decided")
    approval.decided_by, approval.decided_at = p.user_id, utcnow()
    approval.status = "approved" if data.decision == "approve" else "rejected"
    audit(db, p, "approval.decision", "approval", approval.id, {"decision": data.decision, "payload_hash": approval.payload_hash})
    if approval.status == "approved":
        job = await enqueue(db, p, "approval", {"approval_id": approval.id})
        return {"approval": serialize(approval), "job_id": job.id}
    return {"approval": serialize(approval)}

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import Principal, check_cookie_origin, current_principal, hash_token, require_role
from app.models.entities import User, Workspace, WorkspaceMember, RefreshToken, Investigation, AgentExecution, ToolExecution, ModelObservation, Incident, DataSource, MCPServer, AuditLog, ModelConfiguration
from app.schemas.contracts import RegisterRequest, LoginRequest, InvestigationCreate, MemberCreate, MemberUpdate, ModelSettings, WorkspaceUpdate
from app.services import auth
from app.services.common import audit, owned, serialize

router = APIRouter()


def set_refresh(response, value):
    response.set_cookie("cortexops_refresh", value, max_age=get_settings().refresh_token_days * 86400, httponly=True,
                        secure=get_settings().cookie_secure, samesite="strict", path="/api/v1/auth")


@router.post("/auth/register", status_code=201)
async def register(data: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db, scope="function")):
    result, secret = await auth.register(db, data)
    await db.commit()
    set_refresh(response, secret)
    return result


@router.post("/auth/login")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db, scope="function")):
    result, secret = await auth.login(db, data)
    await db.commit()
    set_refresh(response, secret)
    return result


@router.post("/auth/refresh")
async def refresh(request: Request, response: Response, cortexops_refresh: str | None = Cookie(default=None), db: AsyncSession = Depends(get_db, scope="function")):
    check_cookie_origin(request)
    if not cortexops_refresh:
        raise HTTPException(401, "Refresh cookie required")
    result, secret = await auth.rotate(db, cortexops_refresh)
    await db.commit()
    set_refresh(response, secret)
    return result


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response, cortexops_refresh: str | None = Cookie(default=None), db: AsyncSession = Depends(get_db, scope="function")):
    check_cookie_origin(request)
    if cortexops_refresh:
        token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(cortexops_refresh)))
        if token:
            await db.execute(update(RefreshToken).where(RefreshToken.family == token.family).values(revoked=True))
    response.delete_cookie("cortexops_refresh", path="/api/v1/auth")


@router.get("/auth/me")
async def me(p: Principal = Depends(current_principal)):
    return {"id": p.user_id, "name": p.name, "email": p.email, "role": p.role, "workspace_id": p.workspace_id}


class WorkspaceSelection(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)


@router.get("/workspaces")
async def workspaces(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    rows = (await db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember).where(WorkspaceMember.user_id == p.user_id).order_by(Workspace.created_at))).all()
    return [{"id": w.id, "name": w.name, "role": role} for w, role in rows]


@router.post("/auth/workspace")
async def select_workspace(data: WorkspaceSelection, request: Request, response: Response, cortexops_refresh: str | None = Cookie(default=None),
                           p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    check_cookie_origin(request)
    member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == p.user_id, WorkspaceMember.workspace_id == data.workspace_id))
    if not member:
        raise HTTPException(404, "Workspace membership not found")
    if cortexops_refresh:
        token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(cortexops_refresh), RefreshToken.user_id == p.user_id))
        if token:
            await db.execute(update(RefreshToken).where(RefreshToken.family == token.family).values(revoked=True))
    principal = Principal(p.user_id, member.workspace_id, member.role, p.email, p.name)
    result, secret = await auth.new_session(db, principal)
    audit(db, principal, "auth.workspace", "workspace", member.workspace_id)
    await db.commit()
    set_refresh(response, secret)
    return result


@router.get("/dashboard")
async def dashboard(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    counts = dict((await db.execute(select(Investigation.status, func.count()).where(Investigation.workspace_id == p.workspace_id).group_by(Investigation.status))).all())
    recent = (await db.scalars(select(Investigation).where(Investigation.workspace_id == p.workspace_id).order_by(Investigation.created_at.desc()).limit(6))).all()
    avg_duration = await db.scalar(select(func.avg(func.extract("epoch", Investigation.completed_at - Investigation.started_at))).where(Investigation.workspace_id == p.workspace_id, Investigation.status == "completed"))
    agents = (await db.execute(select(AgentExecution.agent, func.count(), func.avg(AgentExecution.duration_ms)).where(AgentExecution.workspace_id == p.workspace_id).group_by(AgentExecution.agent))).all()
    tools = (await db.execute(select(ToolExecution.tool, ToolExecution.status, func.count()).where(ToolExecution.workspace_id == p.workspace_id).group_by(ToolExecution.tool, ToolExecution.status))).all()
    trends = (await db.execute(select(ModelObservation.version, func.avg(ModelObservation.correct.cast(__import__('sqlalchemy').Integer)), func.count()).where(ModelObservation.workspace_id == p.workspace_id).group_by(ModelObservation.version))).all()
    incidents = (await db.scalars(select(Incident).where(Incident.workspace_id == p.workspace_id).order_by(Incident.created_at.desc()).limit(4))).all()
    return {"counts": counts, "total": sum(counts.values()), "average_duration_seconds": avg_duration,
            "recent": [serialize(x) for x in recent], "agent_statistics": [{"agent": a, "count": c, "average_duration_ms": d} for a, c, d in agents],
            "tool_statistics": [{"tool": t, "status": s, "count": c} for t, s, c in tools],
            "model_trends": [{"version": v, "accuracy": float(a), "samples": n} for v, a, n in trends], "incidents": [serialize(x) for x in incidents]}


@router.get("/investigations")
async def list_investigations(limit: int = 50, offset: int = 0, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    rows = await db.scalars(select(Investigation).where(Investigation.workspace_id == p.workspace_id).order_by(Investigation.created_at.desc()).offset(max(0, offset)).limit(max(1, min(limit, 100))))
    return [serialize(x) for x in rows]


@router.post("/investigations", status_code=201)
async def create_investigation(data: InvestigationCreate, p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db, scope="function")):
    item = Investigation(workspace_id=p.workspace_id, created_by=p.user_id, **data.model_dump())
    db.add(item)
    await db.flush()
    audit(db, p, "investigation.create", "investigation", item.id)
    return serialize(item)


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return serialize(await owned(db, Investigation, investigation_id, p))


@router.get("/workspace")
async def workspace(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return serialize(await db.get(Workspace, p.workspace_id))


@router.patch("/workspace")
async def update_workspace(data: WorkspaceUpdate, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    item = await db.get(Workspace, p.workspace_id)
    item.name = data.name.strip()
    audit(db, p, "workspace.update", "workspace", item.id)
    return serialize(item)


@router.get("/members")
async def members(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    rows = (await db.execute(select(WorkspaceMember, User).join(User).where(WorkspaceMember.workspace_id == p.workspace_id))).all()
    return [{"id": m.id, "user_id": u.id, "role": m.role, "email": u.email, "name": u.name} for m, u in rows]


@router.post("/members", status_code=201)
async def add_member(data: MemberCreate, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    if data.role == "admin" and p.role != "owner":
        raise HTTPException(403, "Only owners may grant admin access")
    user = await db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if not user:
        raise HTTPException(404, "User must register before joining a workspace")
    if await db.scalar(select(WorkspaceMember.id).where(WorkspaceMember.workspace_id == p.workspace_id, WorkspaceMember.user_id == user.id)):
        raise HTTPException(409, "User is already a member")
    item = WorkspaceMember(workspace_id=p.workspace_id, user_id=user.id, role=data.role)
    db.add(item)
    await db.flush()
    audit(db, p, "member.create", "member", item.id, {"role": data.role})
    return serialize(item)


@router.patch("/members/{member_id}")
async def update_member(member_id: str, data: MemberUpdate, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    item = await owned(db, WorkspaceMember, member_id, p, lock=True)
    if item.role == "owner" or item.user_id == p.user_id or (p.role != "owner" and (item.role == "admin" or data.role == "admin")):
        raise HTTPException(403, "This role change requires the workspace owner")
    item.role = data.role
    audit(db, p, "member.update", "member", item.id, {"role": data.role})
    return serialize(item)


@router.get("/settings/model")
async def model_config(p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    return serialize(await db.scalar(select(ModelConfiguration).where(ModelConfiguration.workspace_id == p.workspace_id)))


@router.put("/settings/model")
async def update_model_config(data: ModelSettings, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    item = await db.scalar(select(ModelConfiguration).where(ModelConfiguration.workspace_id == p.workspace_id))
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    audit(db, p, "model.configure", "model_configuration", item.id, data.model_dump())
    return serialize(item)


@router.get("/audit")
async def audit_logs(limit: int = 100, p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    return [serialize(x) for x in await db.scalars(select(AuditLog).where(AuditLog.workspace_id == p.workspace_id).order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 500))))]


@router.get("/data-sources")
async def sources(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return [serialize(x) for x in await db.scalars(select(DataSource).where(DataSource.workspace_id == p.workspace_id))]


@router.get("/mcp/servers")
async def servers(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return [serialize(x) for x in await db.scalars(select(MCPServer).where(MCPServer.workspace_id == p.workspace_id))]

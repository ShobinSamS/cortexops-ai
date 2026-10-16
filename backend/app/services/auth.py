from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from app.core.security import Principal, hash_token, issue_token, passwords, refresh_secret
from app.models.entities import RefreshToken, User, Workspace, WorkspaceMember, ModelConfiguration, DataSource, MCPServer, utcnow
from app.services.common import audit
from app.core.config import get_settings

SERVER_PORTS = {"github": 8101, "analytics": 8102, "knowledge": 8103, "monitoring": 8104, "incidents": 8105}


def mcp_endpoint(kind):
    s = get_settings()
    host = f"http://mcp-{kind}" if s.mcp_container_network else s.mcp_base_url
    return f"{host}:{SERVER_PORTS[kind] + s.mcp_port_offset}/mcp"


READ_TOOLS = {
    "github": ["list_repositories", "get_recent_commits", "compare_commits", "get_pull_requests", "get_changed_files", "create_issue"],
    "analytics": ["get_model_metrics", "compare_model_versions", "get_failure_distribution", "get_deployment_statistics"],
    "knowledge": ["search_knowledge", "get_document", "retrieve_evidence"],
    "monitoring": ["get_application_logs", "get_error_statistics", "get_service_health", "get_deployment_events"],
    "incidents": ["list_incidents", "get_incident", "create_incident"],
}


async def new_session(db, principal, family=None):
    secret = refresh_secret()
    db.add(RefreshToken(user_id=principal.user_id, workspace_id=principal.workspace_id, token_hash=hash_token(secret),
                        family=family or str(uuid4()), expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days)))
    return {"access_token": issue_token(principal), "token_type": "bearer", "user": {"id": principal.user_id, "email": principal.email, "name": principal.name, "role": principal.role, "workspace_id": principal.workspace_id}}, secret


async def register(db, data):
    if await db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(409, "Email is already registered")
    import asyncio
    password_hash = await asyncio.to_thread(passwords.hash, data.password)
    user = User(email=data.email, name=data.name.strip(), password_hash=password_hash)
    workspace = Workspace(name=data.workspace_name.strip())
    db.add_all([user, workspace])
    await db.flush()
    db.add(WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role="owner"))
    db.add(ModelConfiguration(workspace_id=workspace.id, model=get_settings().ollama_model))
    for kind, port in SERVER_PORTS.items():
        db.add(MCPServer(workspace_id=workspace.id, name=f"{kind.title()} MCP", kind=kind,
                          url=mcp_endpoint(kind), allowed_tools=READ_TOOLS[kind]))
        db.add(DataSource(workspace_id=workspace.id, name=f"{kind.title()} source", kind=kind, mode="synthetic"))
    principal = Principal(user.id, workspace.id, "owner", user.email, user.name)
    audit(db, principal, "auth.register", "user", user.id)
    return await new_session(db, principal)


async def login(db, data):
    user = await db.scalar(select(User).where(User.email == data.email.strip().lower(), User.is_active.is_(True)))
    import asyncio
    # A fixed valid dummy hash would avoid existence-dependent timing; perform a hash
    # when the account is missing so a nonexistent account also pays Argon2 cost.
    if user is None:
        await asyncio.to_thread(passwords.hash, data.password)
        raise HTTPException(401, "Email or password is incorrect")
    if not await asyncio.to_thread(passwords.verify, data.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at))
    if member is None:
        raise HTTPException(403, "No workspace membership")
    principal = Principal(user.id, member.workspace_id, member.role, user.email, user.name)
    audit(db, principal, "auth.login", "user", user.id)
    return await new_session(db, principal)


async def rotate(db, secret):
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(secret)).with_for_update())
    if token is None:
        raise HTTPException(401, "Invalid refresh token")
    if token.used_at is not None or token.revoked:
        await db.execute(update(RefreshToken).where(RefreshToken.family == token.family).values(revoked=True))
        await db.commit()  # Persist family revocation even though the request is rejected.
        raise HTTPException(401, "Refresh token reused; session revoked")
    if token.expires_at <= utcnow():
        raise HTTPException(401, "Refresh token expired")
    user = await db.get(User, token.user_id)
    member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == token.user_id, WorkspaceMember.workspace_id == token.workspace_id))
    if user is None or not user.is_active or member is None:
        raise HTTPException(401, "Session is no longer valid")
    token.used_at = utcnow()
    principal = Principal(user.id, member.workspace_id, member.role, user.email, user.name)
    return await new_session(db, principal, token.family)

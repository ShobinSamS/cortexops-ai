from dataclasses import dataclass
from datetime import timedelta
import hashlib
import secrets
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.entities import User, WorkspaceMember, utcnow

passwords = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)
ROLES = {"viewer": 0, "analyst": 1, "admin": 2, "owner": 3}


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str
    email: str = ""
    name: str = ""


def issue_token(principal: Principal, audience="cortexops", minutes=None, investigation_id=None):
    settings = get_settings()
    now = utcnow()
    return jwt.encode({"sub": principal.user_id, "wid": principal.workspace_id, "iss": "cortexops-ai", "aud": audience,
                       "iat": now, "exp": now + timedelta(minutes=minutes or settings.access_token_minutes), "jti": str(uuid4()),
                       "iid": investigation_id}, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, audience="cortexops"):
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=audience, issuer="cortexops-ai", options={"require": ["exp", "sub", "wid", "iat", "jti"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired access token") from exc


async def principal_from_token(token: str, db: AsyncSession, audience="cortexops"):
    claims = decode_token(token, audience)
    row = (await db.execute(select(User, WorkspaceMember).join(WorkspaceMember, WorkspaceMember.user_id == User.id).where(
        User.id == claims["sub"], User.is_active.is_(True), WorkspaceMember.workspace_id == claims["wid"]))).first()
    if not row:
        raise HTTPException(401, "Session membership is no longer valid")
    user, member = row
    return Principal(user.id, member.workspace_id, member.role, user.email, user.name)


async def current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)):
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    return await principal_from_token(credentials.credentials, db)


def require_role(minimum: str):
    async def dependency(principal: Principal = Depends(current_principal)):
        if ROLES[principal.role] < ROLES[minimum]:
            raise HTTPException(403, f"{minimum.title()} permission required")
        return principal
    return dependency


def hash_token(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def refresh_secret():
    return secrets.token_urlsafe(48)


def check_cookie_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin not in get_settings().allowed_origins.split(","):
        raise HTTPException(403, "Untrusted request origin")

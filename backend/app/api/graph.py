from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import Principal, current_principal, require_role
from app.services.graph import graph_snapshot
from app.services.jobs import enqueue
from app.services.common import audit

router = APIRouter()


@router.get("/graph")
async def graph(p: Principal = Depends(current_principal)):
    return await graph_snapshot(p.workspace_id)


@router.post("/graph/sync", status_code=202)
async def sync(p: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db, scope="function")):
    job = await enqueue(db, p, "graph_sync", {})
    audit(db, p, "graph.sync", "workspace", p.workspace_id)
    return {"job_id": job.id}

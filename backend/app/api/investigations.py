import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Session, get_db
from app.core.security import Principal, current_principal, principal_from_token, require_role
from app.models.entities import Investigation, InvestigationStep, AgentExecution, InvestigationEvent, ToolExecution, BackgroundJob
from app.services.common import audit, owned, serialize
from app.services.jobs import enqueue
from app.services.events import emit
from app.agents.workflow import AGENTS

router = APIRouter()


@router.post("/investigations/{investigation_id}/{action}")
async def control(investigation_id: str, action: str, p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db, scope="function")):
    if action not in {"start", "pause", "resume", "cancel"}:
        raise HTTPException(404, "Unknown investigation action")
    item = await owned(db, Investigation, investigation_id, p, lock=True)
    if action in {"start", "resume"}:
        if (action == "start" and item.status != "draft") or (action == "resume" and item.status not in {"failed", "paused"}):
            raise HTTPException(409, "Investigation cannot enter that lifecycle state")
        if item.job_id:
            old_job = await db.get(BackgroundJob, item.job_id)
            if old_job and old_job.status in {"queued", "running"}:
                raise HTTPException(409, "The current worker is still reaching a safe checkpoint; try again shortly")
        if action == "start":
            db.add_all([InvestigationStep(workspace_id=p.workspace_id, investigation_id=item.id, agent=agent, position=i) for i, agent in enumerate(AGENTS)])
        if item.status != "paused":
            item.status = "queued"
        item.error = None
        audit(db, p, f"investigation.{action}", "investigation", item.id)
        job = await enqueue(db, p, "investigation", {"investigation_id": item.id, "resume": action == "resume"}, investigation=item)
        return {"investigation": serialize(item), "job_id": job.id}
    if action == "pause":
        if item.status not in {"running", "queued"}:
            raise HTTPException(409, "Only queued or running investigations can be paused")
        item.status = "paused"
    else:
        if item.status in {"completed", "cancelled"}:
            raise HTTPException(409, "Investigation is already terminal")
        item.status = "cancelled"
    audit(db, p, f"investigation.{action}", "investigation", item.id)
    await db.commit()
    await emit(item.id, f"investigation.{item.status}", data={"requested_by": p.user_id, "cooperative": True})
    return {"investigation": serialize(item)}


@router.get("/investigations/{investigation_id}/steps")
async def steps(investigation_id: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    await owned(db, Investigation, investigation_id, p)
    rows = list(await db.scalars(select(InvestigationStep).where(InvestigationStep.investigation_id == investigation_id, InvestigationStep.workspace_id == p.workspace_id).order_by(InvestigationStep.position)))
    executions = list(await db.scalars(select(AgentExecution).where(AgentExecution.investigation_id == investigation_id, AgentExecution.workspace_id == p.workspace_id).order_by(AgentExecution.created_at)))
    return {"steps": [serialize(x) for x in rows], "executions": [serialize(x) for x in executions]}


@router.get("/investigations/{investigation_id}/events")
async def events(investigation_id: str, after: int = 0, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    await owned(db, Investigation, investigation_id, p)
    return [serialize(x) for x in await db.scalars(select(InvestigationEvent).where(InvestigationEvent.investigation_id == investigation_id, InvestigationEvent.workspace_id == p.workspace_id, InvestigationEvent.sequence > max(0, after)).order_by(InvestigationEvent.sequence).limit(1000))]


@router.get("/investigations/{investigation_id}/tools")
async def tools(investigation_id: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    await owned(db, Investigation, investigation_id, p)
    return [serialize(x) for x in await db.scalars(select(ToolExecution).where(ToolExecution.investigation_id == investigation_id, ToolExecution.workspace_id == p.workspace_id).order_by(ToolExecution.created_at).limit(100))]


@router.websocket("/ws/investigations/{investigation_id}")
async def websocket(websocket: WebSocket, investigation_id: str):
    origin = websocket.headers.get("origin")
    from app.core.config import get_settings
    if origin and origin not in get_settings().allowed_origins.split(","):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    key = None
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(first) > 8192:
            await websocket.close(code=4400)
            return
        credentials = json.loads(first)
        token, cursor = credentials.get("token", ""), max(0, int(credentials.get("after", 0)))
        async with Session() as db:
            p = await principal_from_token(token, db)
            await owned(db, Investigation, investigation_id, p)
        key = f"ws:{p.user_id}"
        count = await websocket.app.state.redis.incr(key)
        await websocket.app.state.redis.expire(key, 60)
        if count > 4:
            await websocket.close(code=4429)
            return
        checked, heartbeat = time.monotonic(), 0.0
        while True:
            async with Session() as db:
                if time.monotonic() - checked > 20:
                    await principal_from_token(token, db)
                    checked = time.monotonic()
                    await websocket.app.state.redis.expire(key, 60)
                item = await owned(db, Investigation, investigation_id, p)
                rows = list(await db.scalars(select(InvestigationEvent).where(InvestigationEvent.investigation_id == investigation_id, InvestigationEvent.workspace_id == p.workspace_id, InvestigationEvent.sequence > cursor).order_by(InvestigationEvent.sequence).limit(100)))
                status = item.status
            for row in rows:
                cursor = row.sequence
                await websocket.send_json({"type": "event", **serialize(row)})
            if time.monotonic() - heartbeat > 5:
                await websocket.send_json({"type": "heartbeat", "status": status, "sequence": cursor})
                heartbeat = time.monotonic()
            if status in {"completed", "cancelled", "failed"} and not rows:
                await websocket.close(code=1000)
                return
            await asyncio.sleep(.5)
    except HTTPException:
        await websocket.close(code=4401)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass
    finally:
        if key:
            try:
                await websocket.app.state.redis.decr(key)
            except Exception:
                pass

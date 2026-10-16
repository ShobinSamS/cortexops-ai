import json
from sqlalchemy import func, select
from redis.asyncio import Redis
from app.core.config import get_settings
from app.core.database import transaction
from app.models.entities import Investigation, InvestigationEvent
from app.services.common import serialize


async def emit(investigation_id, kind, agent=None, data=None):
    async with transaction() as db:
        item = await db.scalar(select(Investigation).where(Investigation.id == investigation_id).with_for_update())
        if item is None:
            return
        sequence = (await db.scalar(select(func.max(InvestigationEvent.sequence)).where(InvestigationEvent.investigation_id == item.id)) or 0) + 1
        event = InvestigationEvent(workspace_id=item.workspace_id, investigation_id=item.id, sequence=sequence, kind=kind, agent=agent, data=data or {})
        db.add(event)
        await db.flush()
        payload = serialize(event)
    # History is durable before notification. A Redis outage cannot erase events.
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.publish(f"investigation:{investigation_id}", json.dumps(payload))
    except Exception:
        pass
    finally:
        await redis.aclose()
    return payload

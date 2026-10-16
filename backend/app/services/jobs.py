from fastapi import HTTPException
from app.models.entities import BackgroundJob


async def enqueue(db, principal, kind, payload, investigation=None):
    job = BackgroundJob(workspace_id=principal.workspace_id, user_id=principal.user_id, kind=kind, payload=payload)
    db.add(job)
    await db.flush()
    if investigation is not None:
        investigation.job_id = job.id
    await db.commit()
    from app.workers.tasks import background_job
    try:
        from app.core.config import get_settings
        queue = get_settings().celery_queue + ".investigations" if kind == "investigation" else get_settings().celery_queue
        background_job.apply_async(args=[job.id], task_id=job.id, queue=queue)
    except Exception as exc:
        job.status, job.error = "failed", "Queue unavailable; retry the operation when Redis is healthy"
        await db.commit()
        raise HTTPException(503, job.error) from exc
    return job

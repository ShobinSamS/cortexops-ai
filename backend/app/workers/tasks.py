import asyncio
import logging
from sqlalchemy import text

from app.core.database import engine, transaction
from app.models.entities import BackgroundJob, Document, utcnow
from app.workers.celery_app import celery
from app.core.telemetry import tracer
import structlog

logger = logging.getLogger("cortexops.worker")
_runner = None


def run_async(coro):
    global _runner
    if _runner is None:
        _runner = asyncio.Runner()
    return _runner.run(coro)


async def execute_job(job_id: str):
    # Session-scoped advisory lock prevents duplicate delivery from executing a job
    # concurrently. A crashed worker releases the connection/lock automatically.
    async with engine.connect() as lease:
        acquired = await lease.scalar(text("SELECT pg_try_advisory_lock(hashtextextended(:id, 0))"), {"id": job_id})
        if not acquired:
            return {"duplicate_delivery": True}
        await lease.commit()  # Session lock survives commit; do not hold a transaction during model work.
        try:
            async with transaction() as db:
                job = await db.get(BackgroundJob, job_id)
                if job is None or job.status == "completed":
                    return {"skipped": True}
                job.status, job.error = "running", None
                kind, wid, payload = job.kind, job.workspace_id, job.payload
            try:
                from app.services.knowledge import ingest_document, search_knowledge, delete_document
                if kind == "ingest":
                    result = await ingest_document(wid, payload["document_id"])
                elif kind == "search":
                    result = {"evidence": await search_knowledge(wid, **payload)}
                elif kind == "delete_document":
                    result = await delete_document(wid, payload["document_id"])
                elif kind == "investigation":
                    from app.agents.workflow import run_investigation
                    result = await run_investigation(payload["investigation_id"], resume=payload.get("resume", False))
                elif kind == "approval":
                    from app.services.approvals import execute_approval
                    result = await execute_approval(payload["approval_id"])
                elif kind == "graph_sync":
                    from app.services.graph import rebuild_graph
                    result = await rebuild_graph(wid)
                else:
                    raise ValueError("Unknown background job kind")
                async with transaction() as db:
                    job = await db.get(BackgroundJob, job_id)
                    job.status, job.result, job.completed_at = "completed", result, utcnow()
                return result
            except Exception as exc:
                logger.exception("Background job failed: %s", job_id)
                # Parser/model errors are safe actionable messages; infrastructure
                # tracebacks remain server-side rather than exposing connection strings.
                message = str(exc)[:500] if isinstance(exc, (ValueError, TimeoutError)) else f"{type(exc).__name__}: background operation failed; inspect worker logs"
                async with transaction() as db:
                    job = await db.get(BackgroundJob, job_id)
                    job.status, job.error, job.completed_at = "failed", message, utcnow()
                    if kind == "ingest":
                        doc = await db.get(Document, payload["document_id"])
                        if doc and doc.workspace_id == wid and doc.status != "deleting":
                            doc.status, doc.error = "failed", message
                raise
        finally:
            await lease.execute(text("SELECT pg_advisory_unlock(hashtextextended(:id, 0))"), {"id": job_id})


@celery.task(name="cortexops.job", bind=True)
def background_job(self, job_id: str):
    with tracer().start_as_current_span("background.job", attributes={"job.id": job_id}):
        structlog.get_logger("cortexops.jobs").info("job.started", job_id=job_id)
        result = run_async(execute_job(job_id))
        structlog.get_logger("cortexops.jobs").info("job.completed", job_id=job_id)
        return result

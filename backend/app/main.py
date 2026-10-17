from contextlib import asynccontextmanager
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, Gauge, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text, select, func
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import engine, Session
from app.core.telemetry import configure_telemetry
from app.models.entities import AgentExecution, ToolExecution, Investigation
import structlog
from app.api.foundation import router as foundation
from app.api.knowledge import router as knowledge
from app.api.demo import router as demo
from app.api.tools import router as tools
from app.api.investigations import router as investigations
from app.api.reports import router as reports
from app.api.graph import router as graph

logger = logging.getLogger("cortexops")
REQUESTS = Counter("cortexops_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("cortexops_http_duration_seconds", "HTTP request duration", ["route"])
PERSISTED_INVESTIGATIONS = Gauge("cortexops_investigations", "Persisted investigation count", ["status"])
PERSISTED_LLM_CALLS = Gauge("cortexops_persisted_llm_calls", "Persisted local model calls across workers")
PERSISTED_TOKENS = Gauge("cortexops_persisted_tokens", "Persisted token usage across workers", ["direction"])
PERSISTED_TOOLS = Gauge("cortexops_persisted_tool_executions", "Persisted tool execution count", ["status"])


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.conninfo import make_conninfo
    # Initialize SDK-managed tables before any worker can hold execution leases.
    async with AsyncPostgresSaver.from_conn_string(make_conninfo(settings.psycopg_url, connect_timeout=5)) as saver:
        await saver.setup()
    yield
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title="CortexOps AI", version="0.1.0", lifespan=lifespan)
configure_telemetry("cortexops-api")
if get_settings().otel_exporter_otlp_endpoint:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health/.*,/metrics")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
app.include_router(foundation, prefix="/api/v1")
app.include_router(knowledge, prefix="/api/v1")
app.include_router(demo, prefix="/api/v1")
app.include_router(tools, prefix="/api/v1")
app.include_router(investigations, prefix="/api/v1")
app.include_router(reports, prefix="/api/v1")
app.include_router(graph, prefix="/api/v1")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    started = time.monotonic()
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        window = int(time.time()) // 60
        is_auth = request.url.path in ("/api/v1/auth/register", "/api/v1/auth/login")
        key = f"rate:{'auth' if is_auth else 'api'}:{request.client.host if request.client else 'unknown'}:{window}"
        try:
            pipeline = request.app.state.redis.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, 70)
            count, _ = await pipeline.execute()
            if count > (15 if is_auth else 240):
                return JSONResponse({"detail": "Rate limit exceeded", "request_id": request.state.request_id}, status_code=429, headers={"Retry-After": "60"})
        except Exception:
            return JSONResponse({"detail": "Rate-limit service unavailable", "request_id": request.state.request_id}, status_code=503)
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")
    REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    LATENCY.labels(route).observe(time.monotonic() - started)
    structlog.get_logger("cortexops.http").info("request.completed", request_id=request.state.request_id, method=request.method, route=route,
                                              status=response.status_code, duration_ms=round((time.monotonic() - started) * 1000, 2))
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({"detail": exc.detail, "request_id": getattr(request.state, "request_id", None)}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not reflect passwords or raw request input in validation responses.
    errors = [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": errors, "request_id": getattr(request.state, "request_id", None)}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return JSONResponse({"detail": "Resource conflicts with an existing record", "request_id": getattr(request.state, "request_id", None)}, status_code=409)


@app.exception_handler(Exception)
async def unexpected(request, exc):
    logger.exception("Unhandled request failure", extra={"request_id": getattr(request.state, "request_id", None)})
    return JSONResponse({"detail": "Unexpected server error", "request_id": getattr(request.state, "request_id", None)}, status_code=500)


@app.get("/health/live")
async def live():
    return {"status": "ok", "service": "cortexops-api"}


@app.get("/health/ready")
async def ready(request: Request):
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await request.app.state.redis.ping()
    except Exception as exc:
        raise HTTPException(503, "Database or Redis unavailable") from exc
    return {"status": "ready", "database": "connected", "redis": "connected"}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    # Database-derived gauges include both Celery queues; process-local counters
    # alone would incorrectly omit worker inference and tool activity.
    async with Session() as db:
        PERSISTED_INVESTIGATIONS.clear()
        for status, count in (await db.execute(select(Investigation.status, func.count()).group_by(Investigation.status))).all():
            PERSISTED_INVESTIGATIONS.labels(status).set(count)
        calls, incoming, outgoing = (await db.execute(select(func.coalesce(func.sum(AgentExecution.llm_calls), 0), func.coalesce(func.sum(AgentExecution.input_tokens), 0), func.coalesce(func.sum(AgentExecution.output_tokens), 0)))).one()
        PERSISTED_LLM_CALLS.set(calls)
        PERSISTED_TOKENS.labels("input").set(incoming)
        PERSISTED_TOKENS.labels("output").set(outgoing)
        PERSISTED_TOOLS.clear()
        for status, count in (await db.execute(select(ToolExecution.status, func.count()).group_by(ToolExecution.status))).all():
            PERSISTED_TOOLS.labels(status).set(count)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

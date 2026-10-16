import logging
from functools import lru_cache

import structlog
from opentelemetry import trace

from app.core.config import get_settings


@lru_cache
def configure_telemetry(service):
    structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
                        logger_factory=structlog.stdlib.LoggerFactory())
    endpoint = get_settings().otel_exporter_otlp_endpoint
    if not endpoint:
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=5)))
    trace.set_tracer_provider(provider)


def tracer():
    return trace.get_tracer("cortexops")

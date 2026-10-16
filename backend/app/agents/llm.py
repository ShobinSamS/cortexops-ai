import asyncio
import json
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from prometheus_client import Counter, Histogram

from app.core.config import get_settings
from app.core.database import transaction
from app.models.entities import AgentExecution, Investigation, ModelConfiguration

LLM_CALLS = Counter("cortexops_llm_calls_total", "Local LLM calls", ["status"])
LLM_LATENCY = Histogram("cortexops_llm_duration_seconds", "Local LLM inference time")
Schema = TypeVar("Schema", bound=BaseModel)


async def structured(schema: type[Schema], system: str, payload: dict, execution_id: str, investigation_id: str) -> Schema:
    settings = get_settings()
    async with transaction() as db:
        investigation = await db.get(Investigation, investigation_id)
        config = await db.scalar(select(ModelConfiguration).where(ModelConfiguration.workspace_id == investigation.workspace_id))
        model, context, temperature = config.model, config.context_window, config.temperature
    messages = [{"role": "system", "content": system + " Return only valid JSON matching the provided schema. /no_think"},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    error = None
    for attempt in range(2):
        async with transaction() as db:
            await db.scalar(select(Investigation.id).where(Investigation.id == investigation_id).with_for_update())
            count = await db.scalar(select(func.coalesce(func.sum(AgentExecution.llm_calls), 0)).where(AgentExecution.investigation_id == investigation_id))
            if count >= settings.max_llm_calls:
                raise ValueError("Investigation LLM-call budget exhausted")
            execution = await db.get(AgentExecution, execution_id)
            execution.llm_calls += 1
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout, connect=10)) as client:
                response = await client.post(settings.ollama_base_url.rstrip("/") + "/api/chat", json={
                    "model": model, "stream": False, "think": False, "keep_alive": "1m", "format": schema.model_json_schema(),
                    "messages": messages, "options": {"num_ctx": context, "num_predict": 800, "temperature": temperature, "num_thread": 4}})
                response.raise_for_status()
                body = response.json()
            async with transaction() as db:
                execution = await db.get(AgentExecution, execution_id)
                execution.input_tokens += int(body.get("prompt_eval_count", 0))
                execution.output_tokens += int(body.get("eval_count", 0))
                execution.llm_duration_ms = (execution.llm_duration_ms or 0) + (time.monotonic() - started) * 1000
            LLM_LATENCY.observe(time.monotonic() - started)
            text = body["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = schema.model_validate_json(text)
            LLM_CALLS.labels("success").inc()
            return parsed
        except (ValidationError, json.JSONDecodeError, KeyError) as exc:
            LLM_CALLS.labels("invalid_output").inc()
            error = exc
            messages.append({"role": "user", "content": "The last response did not match the JSON schema. Repair it with exact field names, valid enum values, and evidence IDs copied exactly from the input. Do not add commentary."})
        except httpx.HTTPError as exc:
            LLM_CALLS.labels("failed").inc()
            raise ValueError(f"Local model request failed ({type(exc).__name__}); verify Ollama and the configured model") from exc
    raise ValueError("Local model did not produce a valid structured response within the repair budget") from error

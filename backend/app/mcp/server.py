import argparse
import asyncio
from typing import Annotated

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from sqlalchemy import select
from starlette.responses import JSONResponse
import uvicorn

from app.core.config import get_settings
from app.core.database import Session
from app.core.security import decode_token, principal_from_token
from app.mcp.context import ToolContext, _context
from app.mcp.contracts import ToolResult
from app.mcp.tools import execute
from app.models.entities import Investigation
from app.services.auth import SERVER_PORTS

Version = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")]
SHA = Annotated[str, Field(pattern=r"^[a-fA-F0-9]{7,40}$")]
ID = Annotated[str, Field(min_length=36, max_length=36)]


class Authentication:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        value = headers.get(b"authorization", b"").decode()
        if not value.startswith("Bearer "):
            return await JSONResponse({"detail": "MCP bearer token required"}, status_code=401)(scope, receive, send)
        try:
            token = value[7:]
            async with Session() as db:
                p = await principal_from_token(token, db, audience="cortexops-mcp")
                iid = decode_token(token, audience="cortexops-mcp").get("iid")
                if iid and not await db.scalar(select(Investigation.id).where(Investigation.id == iid, Investigation.workspace_id == p.workspace_id)):
                    raise HTTPException(403, "Investigation scope mismatch")
        except HTTPException as exc:
            return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
        marker = _context.set(ToolContext(p, iid))
        try:
            await self.app(scope, receive, send)
        finally:
            _context.reset(marker)


def create_server(kind):
    mcp = FastMCP(f"CortexOps {kind}", stateless_http=True, json_response=True,
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                      allowed_hosts=["127.0.0.1:*", "localhost:*", f"mcp-{kind}:*", "host.docker.internal:*"],
                      allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]))
    if kind == "analytics":
        @mcp.tool()
        async def get_model_metrics(version: Version | None = None) -> ToolResult:
            """Aggregate recorded model accuracy, sample count, confidence and latency using a read-only database view."""
            return await execute(kind, "get_model_metrics", {"version": version})
        @mcp.tool()
        async def compare_model_versions(baseline: Version, candidate: Version) -> ToolResult:
            """Compare stratified accuracies and approximate uncertainty intervals between two observed versions."""
            return await execute(kind, "compare_model_versions", {"baseline": baseline, "candidate": candidate})
        @mcp.tool()
        async def get_failure_distribution(version: Version) -> ToolResult:
            """Count failures per observed document category."""
            return await execute(kind, "get_failure_distribution", {"version": version})
        @mcp.tool()
        async def get_deployment_statistics() -> ToolResult:
            """Read recorded deployment versions, model hashes and configuration."""
            return await execute(kind, "get_deployment_statistics", {})
    elif kind == "github":
        @mcp.tool()
        async def list_repositories() -> ToolResult:
            """List explicitly connected live repositories or persisted synthetic repository records."""
            return await execute(kind, "list_repositories", {})
        @mcp.tool()
        async def get_recent_commits() -> ToolResult:
            """Retrieve recent recorded commits, changed files and patches for the authorized workspace."""
            return await execute(kind, "get_recent_commits", {})
        @mcp.tool()
        async def compare_commits(baseline: SHA, candidate: SHA) -> ToolResult:
            """Compare two commit references in the configured repository."""
            return await execute(kind, "compare_commits", {"baseline": baseline, "candidate": candidate})
        @mcp.tool()
        async def get_pull_requests() -> ToolResult:
            """Read real GitHub pull requests when configured; disclose absent synthetic PR records."""
            return await execute(kind, "get_pull_requests", {})
        @mcp.tool()
        async def get_changed_files(sha: SHA) -> ToolResult:
            """Inspect files and diff for a validated commit SHA."""
            return await execute(kind, "get_changed_files", {"sha": sha})
        @mcp.tool()
        async def create_issue(title: Annotated[str, Field(min_length=3, max_length=160)], body: Annotated[str, Field(min_length=1, max_length=8000)], approval_id: ID) -> ToolResult:
            """WRITE: create a real GitHub issue or local synthetic incident only with an approved exact-payload authorization."""
            return await execute(kind, "create_issue", {"title": title, "body": body, "approval_id": approval_id})
    elif kind == "knowledge":
        @mcp.tool()
        async def search_knowledge(query: Annotated[str, Field(min_length=2, max_length=2000)], limit: Annotated[int, Field(ge=1, le=12)] = 6) -> ToolResult:
            """Queue hybrid retrieval and reranking; return only workspace-owned indexed chunks with provenance."""
            return await execute(kind, "search_knowledge", {"query": query, "limit": limit})
        @mcp.tool()
        async def get_document(document_id: ID) -> ToolResult:
            """Read up to twenty canonical chunks of an indexed workspace document."""
            return await execute(kind, "get_document", {"document_id": document_id})
        @mcp.tool()
        async def retrieve_evidence(chunk_ids: Annotated[list[ID], Field(min_length=1, max_length=20)]) -> ToolResult:
            """Rehydrate cited canonical chunks, excluding deleted or foreign-workspace records."""
            return await execute(kind, "retrieve_evidence", {"chunk_ids": chunk_ids})
    elif kind == "monitoring":
        @mcp.tool()
        async def get_application_logs(limit: Annotated[int, Field(ge=1, le=100)] = 30) -> ToolResult:
            """Retrieve bounded persisted application logs for this workspace."""
            return await execute(kind, "get_application_logs", {"limit": limit})
        @mcp.tool()
        async def get_error_statistics() -> ToolResult:
            """Aggregate recorded log levels by deployment version."""
            return await execute(kind, "get_error_statistics", {})
        @mcp.tool()
        async def get_service_health() -> ToolResult:
            """Summarize historical service signals without inventing current production health."""
            return await execute(kind, "get_service_health", {})
        @mcp.tool()
        async def get_deployment_events() -> ToolResult:
            """Read recorded deployment chronology and configuration."""
            return await execute(kind, "get_deployment_events", {})
    else:
        @mcp.tool()
        async def list_incidents() -> ToolResult:
            """List persisted incidents in the current workspace."""
            return await execute(kind, "list_incidents", {})
        @mcp.tool()
        async def get_incident(incident_id: ID) -> ToolResult:
            """Inspect one workspace incident."""
            return await execute(kind, "get_incident", {"incident_id": incident_id})
        @mcp.tool()
        async def create_incident(title: Annotated[str, Field(min_length=3, max_length=160)], body: Annotated[str, Field(min_length=1, max_length=8000)], approval_id: ID) -> ToolResult:
            """WRITE: create a local incident only after exact-payload human approval."""
            return await execute(kind, "create_incident", {"title": title, "body": body, "approval_id": approval_id})
    return Authentication(mcp.streamable_http_app())


async def main(kind):
    await uvicorn.Server(uvicorn.Config(create_server(kind), host=get_settings().mcp_bind_host, port=SERVER_PORTS[kind] + get_settings().mcp_port_offset, log_level="warning")).serve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=list(SERVER_PORTS), required=True)
    asyncio.run(main(parser.parse_args().kind))

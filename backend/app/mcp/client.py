from contextlib import asynccontextmanager
from datetime import timedelta
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import Session
from app.core.security import issue_token
from app.models.entities import MCPServer
from app.services.auth import mcp_endpoint


@asynccontextmanager
async def connection(kind, principal, investigation_id=None):
    async with Session() as db:
        server = await db.scalar(select(MCPServer).where(MCPServer.workspace_id == principal.workspace_id, MCPServer.kind == kind))
        expected = mcp_endpoint(kind)
        # Display URLs are rewritten by the explicit operator setup command when
        # switching native/container execution. Runtime never follows a DB URL.
        if server is None:
            raise ValueError("MCP server is not an approved configured endpoint")
    token = issue_token(principal, audience="cortexops-mcp", minutes=15, investigation_id=investigation_id)
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=httpx.Timeout(135, connect=10), follow_redirects=False) as transport:
        async with streamable_http_client(expected, http_client=transport) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def discover(kind, principal):
    async with connection(kind, principal) as session:
        result = await session.list_tools()
        return [{"name": tool.name, "description": tool.description, "input_schema": tool.inputSchema, "output_schema": tool.outputSchema,
                 "requires_approval": tool.name in {"create_issue", "create_incident"}} for tool in result.tools]


async def invoke(kind, tool, arguments, principal, investigation_id=None):
    async with connection(kind, principal, investigation_id) as session:
        result = await session.call_tool(tool, arguments, read_timeout_seconds=timedelta(seconds=130))
        if result.isError:
            messages = [item.text for item in result.content if item.type == "text"]
            raise ValueError("MCP tool rejected the call: " + " ".join(messages)[:600])
        if result.structuredContent:
            return result.structuredContent
        for item in result.content:
            if item.type == "text":
                return json.loads(item.text)
        raise ValueError("MCP server returned no structured result")

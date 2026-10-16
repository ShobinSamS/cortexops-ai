from contextvars import ContextVar
from dataclasses import dataclass
from app.core.security import Principal


@dataclass(frozen=True)
class ToolContext:
    principal: Principal
    investigation_id: str | None = None


_context: ContextVar[ToolContext | None] = ContextVar("mcp_context", default=None)


def current_context() -> ToolContext:
    value = _context.get()
    if value is None:
        raise PermissionError("Authenticated MCP request context required")
    return value

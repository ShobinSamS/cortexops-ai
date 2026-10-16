# MCP server entry points

Implementation is owned once in `backend/app/mcp/`; these servers are real
Streamable HTTP servers using the official MCP Python SDK, not duplicate tools.
From `backend/`, launch one kind per process:

```powershell
.\.venv\Scripts\python.exe -m app.mcp.server --kind github
.\.venv\Scripts\python.exe -m app.mcp.server --kind analytics
.\.venv\Scripts\python.exe -m app.mcp.server --kind knowledge
.\.venv\Scripts\python.exe -m app.mcp.server --kind monitoring
.\.venv\Scripts\python.exe -m app.mcp.server --kind incidents
```

The five commands occupy ports 8101–8105 respectively. Use separate terminals or
the development launcher when available. Each request requires a short-lived
MCP-audience JWT issued by the application. Workspace membership, configured tool
permission and investigation scope are checked on the server. No caller-supplied
workspace parameter is trusted. The workbench uses the official client SDK.

Analytics uses only approved read-only views via separately generated credentials.
Provision them with `python -m app.cli setup-analytics` after migrations.
Knowledge retrieval is queued to Celery; keep the worker running.

Live GitHub is enabled only when GITHUB_TOKEN, GITHUB_REPOSITORY and
GITHUB_WORKSPACE_ID are configured by the operator. Other workspaces use their
persisted synthetic repository records. In synthetic mode, an approved issue
write creates a real local incident record, explicitly labeled in the result.
No synthetic result claims that a GitHub issue was created.

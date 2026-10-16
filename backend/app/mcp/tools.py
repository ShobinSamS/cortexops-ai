import asyncio
from datetime import timedelta
import json
import re
import time

import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import Session, transaction
from app.core.security import ROLES, hash_token
from app.mcp.context import current_context
from app.mcp.contracts import ToolResult
from app.models.entities import MCPServer, ToolExecution, AuditLog, RepositoryChange, ApplicationLog, Deployment, Incident, Document, DocumentChunk, Approval, BackgroundJob, utcnow
from app.services.common import serialize
from app.mcp import analytics
from app.services.destinations import authorization_hash, write_target

WRITE_TOOLS = {"create_issue", "create_incident"}


def evidence(tool, title, content, reference=None):
    import hashlib
    digest = hashlib.sha256((tool + json.dumps(reference or {}, sort_keys=True) + content).encode()).hexdigest()[:24]
    return {"id": f"{tool}:{digest}", "source": tool, "title": title, "content": content[:14000], "reference": reference or {}}


async def read_operational(kind, name, args):
    ctx = current_context()
    p = ctx.principal
    settings = get_settings()
    if kind == "analytics":
        if name == "get_model_metrics":
            data = {"metrics": await analytics.metrics(p.workspace_id, args.get("version"))}
        elif name == "compare_model_versions":
            data = await analytics.comparison(p.workspace_id, args["baseline"], args["candidate"])
        elif name == "get_failure_distribution":
            data = {"categories": await analytics.failures(p.workspace_id, args["version"])}
        else:
            data = {"deployments": await analytics.deployments(p.workspace_id)}
        return ToolResult(source="postgresql_readonly_views", data=data,
                          evidence=[evidence(name, name.replace("_", " "), json.dumps(data), {"tool": name, "workspace_id": p.workspace_id, "query": args})])
    if kind == "knowledge":
        if name == "search_knowledge":
            from app.services.jobs import enqueue
            async with Session() as db:
                job = await enqueue(db, p, "search", {"query": args["query"], "limit": args["limit"], "document_ids": []})
                job_id = job.id
            for _ in range(230):
                async with Session() as db:
                    job = await db.get(BackgroundJob, job_id)
                    if job.status == "failed":
                        raise ValueError(job.error)
                    if job.status == "completed":
                        return ToolResult(source="workspace_knowledge", evidence=job.result.get("evidence", []), data={"job_id": job_id})
                await asyncio.sleep(.5)
            raise TimeoutError("Knowledge retrieval worker did not respond within its budget")
        async with Session() as db:
            if name == "get_document":
                doc = await db.scalar(select(Document).where(Document.id == args["document_id"], Document.workspace_id == p.workspace_id, Document.status == "indexed"))
                if doc is None:
                    raise ValueError("Indexed document not found in this workspace")
                chunks = list(await db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.workspace_id == p.workspace_id).order_by(DocumentChunk.position).limit(20)))
            else:
                chunks = list(await db.scalars(select(DocumentChunk).join(Document, Document.id == DocumentChunk.document_id).where(DocumentChunk.id.in_(args["chunk_ids"]), DocumentChunk.workspace_id == p.workspace_id, Document.status == "indexed")))
            return ToolResult(source="workspace_knowledge", evidence=[{"id": c.id, "source": "knowledge", "title": f"Document chunk {c.position + 1}", "content": c.content,
                "reference": {"document_id": c.document_id, "chunk_id": c.id, "page": c.page, "section": c.section}} for c in chunks])
    if kind == "github":
        external = bool(settings.github_token and settings.github_repository and p.workspace_id == settings.github_workspace_id)
        if external:
            return await github_read(name, args)
        async with Session() as db:
            changes = list(await db.scalars(select(RepositoryChange).where(RepositoryChange.workspace_id == p.workspace_id).order_by(RepositoryChange.committed_at.desc()).limit(30)))
            if name == "list_repositories":
                data = {"repositories": sorted({x.repository for x in changes})}
            elif name == "get_pull_requests":
                return ToolResult(source="synthetic_repository_records", data={"pull_requests": []}, limitations=["The synthetic dataset has commits but no pull-request records. Configure the allowed workspace's real GitHub connection for live PRs."])
            elif name == "get_changed_files":
                change = next((c for c in changes if c.sha == args["sha"]), None)
                if change is None:
                    raise ValueError("Commit not found in workspace repository records")
                data = {"sha": change.sha, "files": change.files, "diff": change.diff}
            elif name == "compare_commits":
                candidate = next((c for c in changes if c.sha == args["candidate"]), None)
                if candidate is None:
                    raise ValueError("Candidate commit not found")
                data = {"baseline": args["baseline"], "candidate": candidate.sha, "files": candidate.files, "diff": candidate.diff}
            else:
                data = {"commits": [serialize(c) for c in changes]}
            return ToolResult(source="synthetic_repository_records", data=data, evidence=[evidence(name, "Recorded repository changes", json.dumps(data), {"mode": "synthetic", "repository": "demo/document-verification"})])
    async with Session() as db:
        if kind == "monitoring":
            logs = list(await db.scalars(select(ApplicationLog).where(ApplicationLog.workspace_id == p.workspace_id).order_by(ApplicationLog.observed_at.desc()).limit(200)))
            if name == "get_deployment_events":
                data = {"deployments": [serialize(x) for x in await db.scalars(select(Deployment).where(Deployment.workspace_id == p.workspace_id).order_by(Deployment.deployed_at.desc()).limit(20))]}
            elif name == "get_error_statistics":
                counts = {}
                for log in logs:
                    key = f"{log.version}:{log.level}"
                    counts[key] = counts.get(key, 0) + 1
                data = {"counts": counts, "sample_size": len(logs)}
            elif name == "get_service_health":
                data = {"service": "document-verification", "observed_log_count": len(logs), "last_observed_at": logs[0].observed_at.isoformat() if logs else None,
                        "status": "recorded_signals_available" if logs else "unknown", "note": "Historical source records do not assert current production availability."}
            else:
                data = {"logs": [serialize(x) for x in logs[:args.get("limit", 30)]]}
            return ToolResult(source="workspace_monitoring_records", data=data, evidence=[evidence(name, name.replace("_", " "), json.dumps(data), {"tool": name})])
        statement = select(Incident).where(Incident.workspace_id == p.workspace_id)
        if name == "get_incident":
            statement = statement.where(Incident.id == args["incident_id"])
        data = {"incidents": [serialize(x) for x in await db.scalars(statement.order_by(Incident.created_at.desc()).limit(30))]}
        return ToolResult(source="workspace_incidents", data=data, evidence=[evidence(name, "Recorded incidents", json.dumps(data), {"tool": name})])


async def github_read(name, args):
    settings = get_settings()
    repository = settings.github_repository
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Configured GitHub repository is invalid")
    paths = {"list_repositories": f"/repos/{repository}", "get_recent_commits": f"/repos/{repository}/commits?per_page=20",
             "get_pull_requests": f"/repos/{repository}/pulls?state=all&per_page=20"}
    if name == "get_changed_files":
        path = f"/repos/{repository}/commits/{args['sha']}"
    elif name == "compare_commits":
        path = f"/repos/{repository}/compare/{args['baseline']}...{args['candidate']}"
    else:
        path = paths[name]
    async with httpx.AsyncClient(base_url="https://api.github.com", timeout=25, follow_redirects=False, headers={"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}) as client:
        response = await client.get(path)
        response.raise_for_status()
        raw = response.json()
    # Bound code/context before it reaches the LLM or public response.
    if isinstance(raw, list):
        raw = raw[:20]
    content = json.dumps(raw)[:20000]
    return ToolResult(source="github_api", data={"repository": repository, "response": raw}, evidence=[evidence(name, f"GitHub {repository}", content, {"repository": repository, "api_path": path})])


async def write_operation(kind, name, args):
    ctx, settings = current_context(), get_settings()
    p = ctx.principal
    approval_id = args.pop("approval_id")
    target = write_target(p.workspace_id, kind, name)
    payload_hash = authorization_hash(args, target)
    async with transaction() as db:
        approval = await db.scalar(select(Approval).where(Approval.id == approval_id, Approval.workspace_id == p.workspace_id).with_for_update())
        if approval is None or approval.target != target or approval.status != "executing" or approval.consumed_at is not None or approval.expires_at <= utcnow() or approval.payload_hash != payload_hash or approval.tool != name or approval.server != kind or approval.decided_by != p.user_id:
            raise PermissionError("A valid, approved, single-use exact-payload authorization is required")
        if ROLES[p.role] < ROLES["admin"]:
            raise PermissionError("Administrator permission is required for external writes")
        approval.consumed_at = utcnow()
    external_url = None
    if name == "create_issue" and settings.github_token and settings.github_repository and p.workspace_id == settings.github_workspace_id:
        repository = settings.github_repository
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Configured repository is invalid")
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers={"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}) as client:
            response = await client.post(f"https://api.github.com/repos/{repository}/issues", json={"title": args["title"], "body": args["body"] + f"\n\n<!-- CortexOps approval {approval_id} -->"})
            response.raise_for_status()
            external_url = response.json()["html_url"]
    async with transaction() as db:
        incident = Incident(workspace_id=p.workspace_id, title=args["title"], description=args.get("body", ""), approval_id=approval_id, external_url=external_url)
        db.add(incident)
        await db.flush()
        return ToolResult(source="github_api" if external_url else "local_incident_store", data={"incident_id": incident.id, "external_url": external_url,
                           "action": "created_github_issue" if external_url else "created_local_incident"})


async def execute(kind: str, name: str, args: dict) -> ToolResult:
    ctx = current_context()
    p = ctx.principal
    async with transaction() as db:
        server = await db.scalar(select(MCPServer).where(MCPServer.workspace_id == p.workspace_id, MCPServer.kind == kind))
        if server is None or name not in server.allowed_tools or ROLES[p.role] < ROLES["analyst"]:
            db.add(AuditLog(workspace_id=p.workspace_id, user_id=p.user_id, action="tool.denied", resource_type="mcp_server", detail={"server": kind, "tool": name}))
            await db.commit()
            raise PermissionError("Tool permission denied for this workspace")
        trace = ToolExecution(workspace_id=p.workspace_id, user_id=p.user_id, investigation_id=ctx.investigation_id, server=kind, tool=name, arguments=args)
        db.add(trace)
        await db.flush()
        trace_id = trace.id
    started, error = time.monotonic(), None
    try:
        async with asyncio.timeout(125):
            result = await write_operation(kind, name, dict(args)) if name in WRITE_TOOLS else await read_operational(kind, name, args)
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: tool operation failed" if not isinstance(exc, (ValueError, PermissionError, TimeoutError)) else str(exc)[:500]
        raise
    finally:
        async with transaction() as db:
            trace = await db.get(ToolExecution, trace_id)
            trace.status, trace.duration_ms, trace.error = "failed" if error else "completed", (time.monotonic() - started) * 1000, error
            trace.result = result.model_dump() if not error and "result" in locals() else {}
            db.add(AuditLog(workspace_id=p.workspace_id, user_id=p.user_id, action="tool.failed" if error else "tool.completed", resource_type="tool_execution", resource_id=trace_id,
                            detail={"server": kind, "tool": name, "investigation_id": ctx.investigation_id}))

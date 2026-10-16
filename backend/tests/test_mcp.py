import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from conftest import account
from test_knowledge import wait_job
from app.core.security import Principal, issue_token


def test_database_role_is_restricted(client):
    with psycopg.connect(os.environ["ANALYTICS_DATABASE_URL"]) as conn:
        assert conn.execute("SELECT count(*) FROM analytics_model_observations").fetchone()[0] >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT password_hash FROM users")
        conn.rollback()
        with pytest.raises((psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)):
            conn.execute("DELETE FROM model_observations")


def test_real_mcp_discovery_metrics_permissions_and_approval(client, worker, mcp_servers):
    account_data, headers = account(client)
    _, outsider = account(client)
    seeded = client.post("/api/v1/demo/seed", headers=headers)
    assert seeded.status_code == 202, seeded.text
    again = client.post("/api/v1/demo/seed", headers=headers)
    assert again.json()["already_seeded"] is True
    servers = client.get("/api/v1/mcp/servers", headers=headers).json()
    for server in servers:
        response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover", headers=headers)
        assert response.status_code == 200, (server["kind"], response.text)
        assert response.json()["tools"]
    metrics = client.post("/api/v1/mcp/tools/invoke", headers=headers, json={"server": "analytics", "tool": "get_model_metrics", "arguments": {}})
    assert metrics.status_code == 200, metrics.text
    values = {row["version"]: row["accuracy"] for row in metrics.json()["data"]["metrics"]}
    assert values["v2.2"] == pytest.approx(.98)
    assert values["v2.3"] == pytest.approx(.91)
    comparison = client.post("/api/v1/mcp/tools/invoke", headers=headers, json={"server": "analytics", "tool": "compare_model_versions", "arguments": {"baseline": "v2.2", "candidate": "v2.3"}})
    assert comparison.status_code == 200, comparison.text
    categories = {row["category"]: row["change_percentage_points"] for row in comparison.json()["data"]["categories"]}
    assert categories["high_resolution"] == 0
    assert categories["low_resolution"] < -20
    token = issue_token(Principal(account_data["user"]["id"], account_data["user"]["workspace_id"], "owner"), audience="cortexops-mcp")
    async def direct_write(approval_id):
        async with streamablehttp_client("http://127.0.0.1:9101/mcp", headers={"Authorization": f"Bearer {token}"}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool("create_issue", {"title": "Approved regression follow-up", "body": "Review the recorded evidence and validate a fix.", "approval_id": approval_id})
    assert asyncio.run(direct_write(str(uuid4()))).isError
    requested = client.post("/api/v1/mcp/tools/invoke", headers=headers, json={"server": "github", "tool": "create_issue", "arguments": {"title": "Approved regression follow-up", "body": "Review the recorded evidence and validate a fix."}})
    assert requested.status_code == 200, requested.text
    approval_id = requested.json()["approval"]["id"]
    assert requested.json()["approval_required"]
    assert requested.json()["approval"]["target"]["mode"] == "local"
    tampered = client.post("/api/v1/mcp/tools/invoke", headers=headers, json={"server": "github", "tool": "create_issue", "arguments": {"title": "Approved regression follow-up", "body": "Review the recorded evidence and validate a fix."}}).json()["approval"]
    with psycopg.connect(os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")) as conn:
        conn.execute("UPDATE approvals SET status='executing', decided_by=%s, target=%s WHERE id=%s", (account_data["user"]["id"], '{"mode":"live","provider":"github","repository":"unexpected/destination"}', tampered["id"]))
    assert asyncio.run(direct_write(tampered["id"])).isError, "Changed destinations must invalidate approval"
    assert client.post(f"/api/v1/approvals/{approval_id}/decision", headers=outsider, json={"decision": "approve"}).status_code == 404
    approved = client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json={"decision": "approve"})
    assert approved.status_code == 200, approved.text
    outcome = wait_job(client, headers, approved.json()["job_id"], timeout=240)
    assert outcome["source"] == "local_incident_store"
    assert outcome["data"]["action"] == "created_local_incident"
    assert client.post(f"/api/v1/approvals/{approval_id}/decision", headers=headers, json={"decision": "approve"}).status_code == 409
    assert asyncio.run(direct_write(approval_id)).isError
    server = next(s for s in servers if s["kind"] == "analytics")
    assert client.patch(f"/api/v1/mcp/servers/{server['id']}/permissions", headers=headers, json={"allowed_tools": []}).status_code == 200
    denied = client.post("/api/v1/mcp/tools/invoke", headers=headers, json={"server": "analytics", "tool": "get_model_metrics", "arguments": {}})
    assert denied.status_code == 403
    history = client.get("/api/v1/mcp/executions", headers=headers).json()
    assert any(x["status"] == "completed" and x["tool"] == "get_model_metrics" for x in history)
    assert any(x["status"] == "failed" and x["tool"] == "create_issue" for x in history)

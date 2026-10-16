import time
from sqlalchemy import select
from conftest import account
from test_knowledge import wait_job


def test_cancel_queued_and_websocket_replay(client):
    _, headers = account(client)
    created = client.post("/api/v1/investigations", headers=headers, json={"title": "Cancelled before execution", "question": "Investigate a request that the user cancels before execution."})
    iid = created.json()["id"]
    assert client.post(f"/api/v1/investigations/{iid}/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/investigations/{iid}/cancel", headers=headers).status_code == 200
    assert client.get(f"/api/v1/investigations/{iid}", headers=headers).json()["status"] == "cancelled"
    with client.websocket_connect(f"/api/v1/ws/investigations/{iid}") as socket:
        socket.send_json({"token": headers["Authorization"].split(" ", 1)[1], "after": 0})
        first = socket.receive_json()
        assert first["type"] == "event" and first["kind"] == "investigation.cancelled"


def test_real_langgraph_investigation_and_checkpoint_resume(client, worker, investigation_worker, mcp_servers):
    _, headers = account(client)
    seeded = client.post("/api/v1/demo/seed", headers=headers)
    assert seeded.status_code == 202, seeded.text
    for job_id in seeded.json()["ingestion_job_ids"]:
        wait_job(client, headers, job_id, timeout=180)
    created = client.post("/api/v1/investigations", headers=headers, json={"title": "Accuracy regression after deployment", "question": "Investigate why document verification accuracy dropped from 98% to 91% after deployment v2.3. Compare preprocessing, source mix and model weights using the evidence."})
    iid = created.json()["id"]
    started = client.post(f"/api/v1/investigations/{iid}/start", headers=headers)
    assert started.status_code == 200, started.text
    # Pause is immediate in the API and cooperative at the next node boundary.
    paused = client.post(f"/api/v1/investigations/{iid}/pause", headers=headers)
    assert paused.status_code == 200, paused.text
    wait_job(client, headers, started.json()["job_id"], timeout=360)
    assert client.get(f"/api/v1/investigations/{iid}", headers=headers).json()["status"] == "paused"
    analytics = next(s for s in client.get("/api/v1/mcp/servers", headers=headers).json() if s["kind"] == "analytics")
    client.patch(f"/api/v1/mcp/servers/{analytics['id']}/permissions", headers=headers, json={"allowed_tools": []})
    resumed = client.post(f"/api/v1/investigations/{iid}/resume", headers=headers)
    assert resumed.status_code == 200, resumed.text
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        failed = client.get(f"/api/v1/jobs/{resumed.json()['job_id']}", headers=headers).json()
        if failed["status"] == "failed":
            break
        assert failed["status"] != "completed", "Revoked tool permission must fail this investigation"
        time.sleep(1)
    assert failed["status"] == "failed"
    assert client.get(f"/api/v1/investigations/{iid}", headers=headers).json()["status"] == "failed"
    client.patch(f"/api/v1/mcp/servers/{analytics['id']}/permissions", headers=headers, json={"allowed_tools": analytics["allowed_tools"]})
    resumed = client.post(f"/api/v1/investigations/{iid}/resume", headers=headers)
    assert resumed.status_code == 200, resumed.text
    result = wait_job(client, headers, resumed.json()["job_id"], timeout=720)
    assert result["status"] == "completed"
    detail = client.get(f"/api/v1/investigations/{iid}", headers=headers).json()
    assert detail["status"] == "completed"
    rows = client.get(f"/api/v1/investigations/{iid}/steps", headers=headers).json()
    assert all(row["status"] == "completed" for row in rows["steps"])
    assert sum(row["llm_calls"] for row in rows["executions"]) >= 2
    assert len([row for row in rows["executions"] if row["agent"] == "planner"]) == 1
    events = client.get(f"/api/v1/investigations/{iid}/events", headers=headers).json()
    assert any(e["kind"] == "investigation.completed" for e in events)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    report = client.get(f"/api/v1/reports/{result['report_id']}", headers=headers)
    assert report.status_code == 200, report.text
    content = report.json()["content"]
    assert content["verified_findings"]
    assert all(f["classification"] == "hypothesis" for f in content["hypotheses"])
    ids = {e["id"] for e in content["evidence"]}
    assert all(set(f["evidence_ids"]).issubset(ids) for f in content["hypotheses"])
    explanation = (content["summary"] + " " + " ".join(f["statement"] for f in content["hypotheses"])).lower()
    assert any(term in explanation for term in ["interpol", "nearest", "resampl"]), explanation

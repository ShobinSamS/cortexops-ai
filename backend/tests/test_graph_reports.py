from io import BytesIO
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from pypdf import PdfReader

from conftest import account
from test_knowledge import wait_job


def connection():
    return psycopg.connect(os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://"))


def test_graph_provenance_isolation_and_rebuild(client, worker):
    data, headers = account(client)
    _, outsider = account(client)
    wid, uid = data["user"]["workspace_id"], data["user"]["id"]
    did, cid = str(uuid4()), str(uuid4())
    with connection() as db:
        db.execute("INSERT INTO documents(id,created_at,workspace_id,uploaded_by,filename,content_type,sha256,storage_path,size_bytes,status,metadata_json) VALUES(%s,now(),%s,%s,'graph-note.md','text/markdown',%s,'not-read-by-graph',120,'indexed','{}')", (did, wid, uid, uuid4().hex))
        db.execute("INSERT INTO document_chunks(id,created_at,workspace_id,document_id,position,content,page,section,metadata_json) VALUES(%s,now(),%s,%s,0,'Service: hermes. Deployment: v7. Repository: demo/hermes.',0,'Release','{}')", (cid, wid, did))
    job = client.post("/api/v1/graph/sync", headers=headers)
    assert job.status_code == 202, job.text
    result = wait_job(client, headers, job.json()["job_id"])
    assert result["nodes"] == 4 and result["edges"] == 3, result
    if os.environ.get("CORTEXOPS_TEST_NEO4J"):
        assert result["projection"]["status"] == "synced", result
    graph = client.get("/api/v1/graph", headers=headers).json()
    assert any(n["kind"] == "service" and n["label"] == "hermes" for n in graph["nodes"])
    assert all(cid in e["evidence"]["chunk_ids"] for e in graph["edges"])
    assert client.get("/api/v1/graph", headers=outsider).json()["nodes"] == []
    stable_ids = {n["id"] for n in graph["nodes"]}
    job = client.post("/api/v1/graph/sync", headers=headers)
    wait_job(client, headers, job.json()["job_id"])
    assert {n["id"] for n in client.get('/api/v1/graph', headers=headers).json()["nodes"]} == stable_ids
    # Rebuild after deletion removes dangling document edges and projection data.
    with connection() as db:
        db.execute("DELETE FROM documents WHERE id=%s", (did,))
    job = client.post("/api/v1/graph/sync", headers=headers)
    wait_job(client, headers, job.json()["job_id"])
    assert client.get("/api/v1/graph", headers=headers).json()["nodes"] == []


def test_report_pdf_markdown_and_access(client):
    data, headers = account(client)
    _, outsider = account(client)
    iid = client.post("/api/v1/investigations", headers=headers, json={"title": "Accuracy regression report", "question": "Investigate a recorded accuracy regression."}).json()["id"]
    rid = str(uuid4())
    content = {"summary": "The recorded preprocessing change is a hypothesis requiring reproduction.", "generated_at": "2026-10-16T12:00:00Z", "outcome": "hypothesis_report",
               "verified_findings": [{"statement": "Accuracy decreased from 98% to 91% across 1,000 samples per version.", "classification": "verified", "confidence": "high", "evidence_ids": ["metrics:1"]}],
               "hypotheses": [{"statement": "Nearest-neighbor resampling may reduce stroke preservation in low-resolution images.", "classification": "hypothesis", "confidence": "medium", "evidence_ids": ["doc:1"], "contradictory_evidence_ids": ["metrics:1"]}],
               "recommendations": ["Reproduce the change on a stratified evaluation set."], "limitations": ["A citation match does not prove causality."],
               "evidence": [{"id": "metrics:1", "source": "analytics", "title": "Version comparison", "content": '{"baseline":0.98,"candidate":0.91}', "reference": {"tool": "compare_model_versions"}},
                            {"id": "doc:1", "source": "knowledge", "title": "Preprocessing contract", "content": "Use bicubic interpolation for RGB thumbnails. <untrusted> & escaped text.", "reference": {"document_id": "demo", "section": "Preprocessing"}}]}
    with connection() as db:
        db.execute("INSERT INTO reports(id,created_at,workspace_id,investigation_id,title,content,markdown) VALUES(%s,now(),%s,%s,'Accuracy regression report',%s,'# Accuracy regression report')", (rid, data["user"]["workspace_id"], iid, json.dumps(content)))
    response = client.get(f"/api/v1/reports/{rid}/export?format=pdf", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert all(x in text for x in ["Verified observations", "Root-cause hypotheses", "98%", "doc:1", "causality", "<untrusted>"])
    output = Path(__file__).resolve().parents[2] / "output/pdf"
    output.mkdir(parents=True, exist_ok=True)
    (output / "sample-investigation-report.pdf").write_bytes(response.content)
    assert client.get(f"/api/v1/reports/{rid}/export?format=md", headers=headers).text.startswith("# Accuracy")
    assert client.get(f"/api/v1/reports/{rid}/export?format=pdf", headers=outsider).status_code == 404
    assert client.get(f"/api/v1/reports/{rid}/export?format=exe", headers=headers).status_code == 400


def test_workspace_switch_checks_membership(client):
    first, owner = account(client)
    second, member = account(client)
    wid = first["user"]["workspace_id"]
    assert client.post("/api/v1/auth/workspace", headers=member, json={"workspace_id": wid}).status_code == 404
    response = client.post("/api/v1/members", headers=owner, json={"email": second["user"]["email"], "role": "viewer"})
    assert response.status_code == 201, response.text
    result = client.post("/api/v1/auth/workspace", headers=member, json={"workspace_id": wid})
    assert result.status_code == 200, result.text
    assert result.json()["user"]["role"] == "viewer"
    switched = {"Authorization": "Bearer " + result.json()["access_token"]}
    assert client.get("/api/v1/workspace", headers=switched).json()["id"] == wid
    assert client.post("/api/v1/graph/sync", headers=switched).status_code == 403

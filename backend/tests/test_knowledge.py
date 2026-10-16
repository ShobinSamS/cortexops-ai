import time
from uuid import uuid4
from pathlib import Path

from conftest import account
from app.rag.parsing import ParsedSection, chunk_sections, parse_file, validate_file
from app.rag.retrieval import sparse_vector


def wait_job(client, headers, job_id, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        if data["status"] == "failed":
            raise AssertionError(data["error"])
        if data["status"] == "completed":
            return data["result"]
        time.sleep(1)
    raise AssertionError("Background job did not complete before the timeout; inspect phase2-test-worker.log")


def test_chunk_identity_overlap_and_sparse_stability():
    sections = [ParsedSection("A documented deployment change. " * 100, 3, "Release")]
    first = chunk_sections("document-a", sections, 500, 80)
    assert first == chunk_sections("document-a", sections, 500, 80)
    assert all(x["page"] == 3 and len(x["content"]) <= 500 for x in first)
    assert len({x["id"] for x in first}) == len(first)
    assert first[0]["id"] != chunk_sections("document-b", sections, 500, 80)[0]["id"]
    assert sparse_vector("Accuracy deployment").model_dump() == sparse_vector("deployment accuracy").model_dump()


def test_upload_validation_and_workspace_bounds(client):
    _, headers = account(client)
    assert client.post("/api/v1/documents", headers=headers, files={"file": ("bad.exe", b"no", "application/octet-stream")}).status_code == 400
    assert client.post("/api/v1/documents", headers=headers, files={"file": ("fake.pdf", b"not a pdf", "application/pdf")}).status_code == 400
    assert client.post("/api/v1/documents", headers=headers, files={"file": ("empty.txt", b"", "text/plain")}).status_code == 400


def test_real_ingestion_hybrid_retrieval_and_delete(client, worker):
    _, headers = account(client)
    _, outsider = account(client)
    marker = uuid4().hex
    content = f"# Deployment note\nService hermes-{marker} switched image interpolation from bicubic to nearest-neighbor. Low-resolution scan accuracy regressed. Rollback restores bicubic."
    uploaded = client.post("/api/v1/documents", headers=headers, files={"file": ("release.md", content.encode(), "text/markdown")})
    assert uploaded.status_code == 202, uploaded.text
    doc_id = uploaded.json()["document"]["id"]
    result = wait_job(client, headers, uploaded.json()["job_id"])
    assert result["chunks"] >= 1
    duplicate = client.post("/api/v1/documents", headers=headers, files={"file": ("copy.md", content.encode(), "text/markdown")})
    assert duplicate.json()["duplicate"] is True
    assert client.get(f"/api/v1/documents/{doc_id}/chunks", headers=outsider).status_code == 404
    assert client.get(f"/api/v1/jobs/{uploaded.json()['job_id']}", headers=outsider).status_code == 404
    search = client.post("/api/v1/knowledge/search", headers=headers, json={"query": f"hermes-{marker} image interpolation accuracy", "limit": 3})
    evidence = wait_job(client, headers, search.json()["job_id"])["evidence"]
    assert evidence and evidence[0]["reference"]["document_id"] == doc_id
    assert evidence[0]["reference"]["page"] == 0
    assert "nearest-neighbor" in evidence[0]["content"]
    other_search = client.post("/api/v1/knowledge/search", headers=outsider, json={"query": f"hermes-{marker} accuracy"})
    assert wait_job(client, outsider, other_search.json()["job_id"])["evidence"] == []
    reindex = client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers)
    assert wait_job(client, headers, reindex.json()["job_id"])["status"] == "indexed"
    deletion = client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
    wait_job(client, headers, deletion.json()["job_id"])
    assert client.get(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 404
    search = client.post("/api/v1/knowledge/search", headers=headers, json={"query": f"hermes-{marker} accuracy"})
    assert wait_job(client, headers, search.json()["job_id"])["evidence"] == []

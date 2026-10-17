"""Real HTTP evaluation; never mocks retrieval, tools, workers, or inference.

Each case gets an isolated evaluation workspace. Cases persist for UI inspection.
Use --investigate to additionally run the CPU model; retrieval-only is the default.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def wait_job(client, job_id, timeout=1500):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get(f"/jobs/{job_id}").raise_for_status().json()
        if result["status"] in {"completed", "failed"}:
            return result
        time.sleep(2)
    raise TimeoutError("Evaluation job exceeded its timeout")


def evaluate(case, base_url, investigate):
    started = time.monotonic()
    with httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", timeout=145) as client:
        registration = client.post("/auth/register", json={"email": f"eval-{uuid4().hex}@example.test", "password": secrets.token_urlsafe(32), "name": "Evaluation runner", "workspace_name": "Evaluation / " + case["id"]}).raise_for_status().json()
        client.headers["Authorization"] = "Bearer " + registration["access_token"]
        result = {"id": case["id"], "category": case["category"], "workspace_id": registration["user"]["workspace_id"]}
        if case.get("seed", True):
            seeded = client.post("/demo/seed").raise_for_status().json()
            for job_id in seeded.get("ingestion_job_ids", []):
                job = wait_job(client, job_id)
                if job["status"] != "completed":
                    raise RuntimeError("Evaluation ingestion failed: " + str(job.get("error")))
        if case.get("retrieval_query"):
            query = client.post("/knowledge/search", json={"query": case["retrieval_query"], "limit": 6}).raise_for_status().json()
            job = wait_job(client, query["job_id"])
            if job["status"] != "completed":
                raise RuntimeError("Retrieval failed: " + str(job.get("error")))
            evidence = job["result"]["evidence"]
            retrieved = {e["reference"]["filename"] for e in evidence}
            relevant = set(case["relevant_documents"])
            result["retrieval"] = {"k": 6, "recall_at_k": len(relevant & retrieved) / len(relevant) if relevant else None,
                                   "precision_at_k": len(relevant & retrieved) / len(retrieved) if retrieved else None,
                                   "irrelevant_abstention": not evidence if not relevant else None,
                                   "retrieved_documents": sorted(retrieved), "scores": [e.get("score") for e in evidence]}
        if investigate:
            if case.get("deny_tool_server"):
                server = next(x for x in client.get("/mcp/servers").raise_for_status().json() if x["kind"] == case["deny_tool_server"])
                client.patch(f"/mcp/servers/{server['id']}/permissions", json={"allowed_tools": []}).raise_for_status()
            item = client.post("/investigations", json={"title": "Evaluation / " + case["id"], "question": case["question"], "selected_sources": case["sources"]}).raise_for_status().json()
            result["investigation_id"] = item["id"]
            started_job = client.post(f"/investigations/{item['id']}/start").raise_for_status().json()
            job = wait_job(client, started_job["job_id"])
            result["job_status"] = job["status"]
            if case.get("expect_status"):
                result["expected_status_match"] = job["status"] == case["expect_status"]
            if job["status"] == "completed" and job["result"].get("report_id"):
                report = client.get(f"/reports/{job['result']['report_id']}").raise_for_status().json()
                content = report["content"]
                ids = {e["id"] for e in content["evidence"]}
                cited = [i for f in content["verified_findings"] + content["hypotheses"] for i in f["evidence_ids"] + f.get("contradictory_evidence_ids", [])]
                result["report_id"], result["outcome"] = report["id"], content["outcome"]
                result["citation_id_validity"] = sum(i in ids for i in cited) / len(cited) if cited else None
                text = (content["summary"] + " ".join(f["statement"] for f in content["hypotheses"])).lower()
                result["expected_term_match"] = any(t in text for t in case.get("expected_hypothesis_terms", [])) if case.get("expected_hypothesis_terms") else None
                if case.get("expect_outcome"):
                    result["expected_outcome_match"] = content["outcome"] == case["expect_outcome"]
        result["duration_seconds"] = round(time.monotonic() - started, 2)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--investigate", action="store_true")
    parser.add_argument("--output", default="evaluation/results.json")
    args = parser.parse_args()
    output_path = (ROOT / args.output).resolve()
    if not output_path.is_relative_to(ROOT):
        raise SystemExit("Evaluation output must stay inside the project directory")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cases = json.loads((ROOT / "evaluation/cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        if args.case and case["id"] not in args.case:
            continue
        if not args.investigate and not case.get("retrieval_query"):
            continue
        try:
            result = evaluate(case, args.base_url, args.investigate)
        except Exception as exc:
            result = {"id": case["id"], "error": f"{type(exc).__name__}: evaluation failed; inspect local service logs"}
        results.append(result)
        print(json.dumps(result), flush=True)
        output_path.write_text(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(), "mode": "investigation" if args.investigate else "retrieval", "limitations": ["Small synthetic dataset; not a general accuracy estimate.", "Citation-ID validity and expected-term matching do not measure semantic entailment or causal correctness."], "results": results}, indent=2), encoding="utf-8")
    raise SystemExit(1 if any("error" in r or any(r.get(k) is False for k in ("expected_status_match", "expected_outcome_match", "expected_term_match")) for r in results) else 0)

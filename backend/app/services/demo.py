from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import random

from fastapi import HTTPException
from sqlalchemy import select
from app.core.config import ROOT, get_settings
from app.core.database import Session
from app.models.entities import Workspace, ModelObservation, Deployment, RepositoryChange, ApplicationLog, Incident, Document
from app.services.common import audit
from app.services.jobs import enqueue


async def seed(db, principal):
    if not get_settings().enable_demo:
        raise HTTPException(403, "Synthetic seeding is disabled in this deployment")
    workspace = await db.scalar(select(Workspace).where(Workspace.id == principal.workspace_id).with_for_update())
    if workspace.settings.get("demo_seed_version") == 1:
        return {"already_seeded": True, "message": "This workspace already contains the reference dataset"}
    rng = random.Random(20261010)
    deployed = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
    rows = []
    for version, failures_low in [("v2.2", 6), ("v2.3", 76)]:
        for category, total, failures in [("high_resolution", 700, 14), ("low_resolution", 300, failures_low)]:
            flags = [False] * failures + [True] * (total - failures)
            rng.shuffle(flags)
            for i, correct in enumerate(flags):
                rows.append(ModelObservation(workspace_id=principal.workspace_id, version=version, category=category, correct=correct,
                            confidence=round(rng.uniform(.89, .99) if correct else rng.uniform(.52, .84), 4),
                            latency_ms=round(rng.uniform(30, 55) if version == "v2.3" else rng.uniform(40, 65), 2),
                            observed_at=deployed + timedelta(hours=1 if version == "v2.3" else -24, seconds=i),
                            metadata_json={"synthetic": True, "label_policy": "consistent-v1"}))
    db.add_all(rows)
    for version, sha, days in [("v2.2", "a" * 40, -7), ("v2.3", "b" * 40, 0)]:
        db.add(Deployment(workspace_id=principal.workspace_id, version=version, service="document-verification", commit_sha=sha,
                         deployed_at=deployed + timedelta(days=days), configuration={"model_hash": "weights-4b17ac", "threshold": .85, "high_resolution_fraction": .7, "low_resolution_fraction": .3, "synthetic": True}))
    changes = [
        ("b" * 40, "Optimize thumbnail preprocessing path", ["verifier/preprocessing.py"], "--- verifier/preprocessing.py\n+++ verifier/preprocessing.py\n- thumbnail = resize(image, (224, 224), interpolation=BICUBIC)\n+ thumbnail = resize(image, (224, 224), interpolation=NEAREST)\n  tensor = normalize(thumbnail, TRAINING_MEAN, TRAINING_STD)"),
        ("c" * 40, "Add structured request tracing", ["verifier/telemetry.py"], "+ span.set_attribute('deployment.version', version)"),
        ("d" * 40, "Clarify dashboard labels", ["frontend/labels.ts"], "- label: 'Verification score'\n+ label: 'Verification confidence'"),
    ]
    for i, (sha, message, files, diff) in enumerate(changes):
        db.add(RepositoryChange(workspace_id=principal.workspace_id, repository="demo/document-verification", sha=sha, message=message,
                                files=files, diff=diff, committed_at=deployed - timedelta(hours=3 + i)))
    for i in range(40):
        version = "v2.2" if i < 10 else "v2.3"
        warning = version == "v2.3" and i % 4 != 0
        db.add(ApplicationLog(workspace_id=principal.workspace_id, service="document-verification", version=version,
                              level="warning" if warning else "info", message="stroke_preservation below 0.30 for low-resolution thumbnail" if warning else "verification request completed",
                              observed_at=deployed + timedelta(hours=1 if version == "v2.3" else -24, minutes=i),
                              metadata_json={"category": "low_resolution" if warning else "high_resolution", "synthetic": True}))
    db.add(Incident(workspace_id=principal.workspace_id, title="Document verification quality changed after v2.3", description="Synthetic alert: investigate accuracy by document category and release. Cause not yet established.", severity="high"))
    directory = get_settings().upload_dir / principal.workspace_id
    directory.mkdir(parents=True, exist_ok=True)
    docs = []
    for source in sorted((ROOT / "demo-data").glob("*.md")):
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        existing = await db.scalar(select(Document).where(Document.workspace_id == principal.workspace_id, Document.sha256 == digest))
        if existing:
            continue
        path = directory / f"demo-{source.name}"
        path.write_bytes(content)
        document = Document(workspace_id=principal.workspace_id, uploaded_by=principal.user_id, filename=source.name, content_type="text/markdown",
                            sha256=digest, storage_path=str(path), size_bytes=len(content), metadata_json={"synthetic": True})
        db.add(document)
        docs.append(document)
    workspace.settings = {**workspace.settings, "demo_seed_version": 1}
    await db.flush()
    audit(db, principal, "demo.seed", "workspace", principal.workspace_id, {"observations": len(rows), "documents": len(docs), "synthetic": True})
    await db.commit()
    jobs = [await enqueue(db, principal, "ingest", {"document_id": doc.id}) for doc in docs]
    return {"already_seeded": False, "observations": len(rows), "documents": len(docs), "ingestion_job_ids": [j.id for j in jobs], "synthetic": True}

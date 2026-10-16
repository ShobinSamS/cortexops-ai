"""Workspace-scoped, provenance-preserving graph with an optional Neo4j projection.

Edges describe recorded relationships and explicit metadata mentions, never LLM
guesses. PostgreSQL remains canonical so disabling Neo4j does not lose evidence.
"""
import re
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import delete, select, text

from app.core.config import get_settings
from app.core.database import Session, transaction
from app.models.entities import (Document, DocumentChunk, Deployment, Incident,
                                 RepositoryChange, GraphEntity, GraphRelationship, Workspace, utcnow)


def stable(workspace_id, kind, key):
    return str(uuid5(NAMESPACE_URL, f"cortexops:{workspace_id}:{kind}:{key}"))


async def rebuild_graph(workspace_id):
    async with transaction() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "graph:" + workspace_id})
        nodes, edges = {}, {}

        def node(kind, key, label, **properties):
            ident = stable(workspace_id, kind, key)
            nodes[ident] = dict(id=ident, workspace_id=workspace_id, kind=kind, source_id=key, label=label[:160], properties=properties)
            return ident

        def link(source, target, kind, **evidence):
            ident = stable(workspace_id, "edge", f"{source}:{target}:{kind}")
            previous = edges.get(ident, {}).get("evidence", {})
            chunk_ids = sorted(set(previous.get("chunk_ids", []) + evidence.get("chunk_ids", [])))
            edges[ident] = dict(id=ident, workspace_id=workspace_id, source_id=source, target_id=target, kind=kind,
                                evidence={**previous, **evidence, **({"chunk_ids": chunk_ids} if chunk_ids else {})})

        docs = list(await db.scalars(select(Document).where(Document.workspace_id == workspace_id, Document.status == "indexed").order_by(Document.created_at).limit(300)))
        for doc in docs:
            chunks = list(await db.scalars(select(DocumentChunk).where(DocumentChunk.workspace_id == workspace_id, DocumentChunk.document_id == doc.id).order_by(DocumentChunk.position).limit(100)))
            source = node("document", doc.id, doc.filename, document_id=doc.id, sha256=doc.sha256, chunk_ids=[c.id for c in chunks])
            for chunk in chunks:
                for kind, value in re.findall(r"\b(Service|Deployment|Repository|Model|Incident):\s*([A-Za-z0-9_./-]{1,120})", chunk.content, re.I):
                    value = value.rstrip(".").lower()
                    target = node(kind.lower(), value, value)
                    link(source, target, "MENTIONS", document_id=doc.id, chunk_ids=[chunk.id], extraction="explicit_metadata")
        for dep in await db.scalars(select(Deployment).where(Deployment.workspace_id == workspace_id).limit(100)):
            release = node("deployment", dep.version.lower(), dep.version, deployment_id=dep.id, deployed_at=dep.deployed_at.isoformat(), commit_sha=dep.commit_sha)
            service = node("service", dep.service.lower(), dep.service)
            link(release, service, "DEPLOYED_TO", record_id=dep.id, source_table="deployments")
        for change in await db.scalars(select(RepositoryChange).where(RepositoryChange.workspace_id == workspace_id).limit(200)):
            repo = node("repository", change.repository.lower(), change.repository)
            commit = node("commit", change.sha, change.message, sha=change.sha, files=change.files)
            link(commit, repo, "COMMITTED_TO", record_id=change.id, source_table="repository_changes")
            for dep in await db.scalars(select(Deployment).where(Deployment.workspace_id == workspace_id, Deployment.commit_sha == change.sha)):
                link(stable(workspace_id, "deployment", dep.version.lower()), commit, "USES_COMMIT", record_id=dep.id, source_table="deployments")
        for incident in await db.scalars(select(Incident).where(Incident.workspace_id == workspace_id).limit(100)):
            source = node("incident", incident.id, incident.title, incident_id=incident.id, status=incident.status)
            target = node("service", incident.service.lower(), incident.service)
            link(source, target, "AFFECTS", record_id=incident.id, source_table="incidents")
        await db.execute(delete(GraphRelationship).where(GraphRelationship.workspace_id == workspace_id))
        await db.execute(delete(GraphEntity).where(GraphEntity.workspace_id == workspace_id))
        db.add_all([GraphEntity(**n) for n in nodes.values()])
        await db.flush()
        db.add_all([GraphRelationship(**e) for e in edges.values()])
    status = await project_neo4j(workspace_id, list(nodes.values()), list(edges.values()))
    async with transaction() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        workspace.settings = {**workspace.settings, "graph_projection": status}
    return {"nodes": len(nodes), "edges": len(edges), "projection": status}


async def project_neo4j(workspace_id, nodes, edges):
    settings = get_settings()
    if not settings.neo4j_uri:
        return {"status": "disabled", "source": "postgresql", "updated_at": utcnow().isoformat()}
    from neo4j import AsyncGraphDatabase
    import asyncio
    try:
        async with asyncio.timeout(12):
            async with AsyncGraphDatabase.driver(settings.neo4j_uri, auth=("neo4j", settings.neo4j_password), connection_timeout=4) as driver:
                async with driver.session() as session:
                    await (await session.run("CREATE CONSTRAINT cortex_entity_id IF NOT EXISTS FOR (n:CortexEntity) REQUIRE n.id IS UNIQUE")).consume()

                    async def replace(tx):
                        await (await tx.run("MATCH (n:CortexEntity {workspace_id:$wid}) DETACH DELETE n", wid=workspace_id)).consume()
                        await (await tx.run("UNWIND $nodes AS row CREATE (n:CortexEntity) SET n = row", nodes=[{k: n[k] for k in ("id", "workspace_id", "kind", "label", "source_id")} for n in nodes])).consume()
                        await (await tx.run("UNWIND $edges AS row MATCH (a:CortexEntity {id:row.source_id,workspace_id:$wid}), (b:CortexEntity {id:row.target_id,workspace_id:$wid}) CREATE (a)-[:RELATED {kind:row.kind,workspace_id:$wid}]->(b)", edges=edges, wid=workspace_id)).consume()
                    await session.execute_write(replace)
        return {"status": "synced", "source": "neo4j", "updated_at": utcnow().isoformat()}
    except Exception:
        # Canonical evidence remains available. Never surface a driver URI/password.
        return {"status": "unavailable", "source": "postgresql", "updated_at": utcnow().isoformat(), "detail": "Neo4j projection unavailable; inspect operator logs and retry sync."}


async def graph_snapshot(workspace_id):
    async with Session() as db:
        nodes = list(await db.scalars(select(GraphEntity).where(GraphEntity.workspace_id == workspace_id).order_by(GraphEntity.kind, GraphEntity.label).limit(1000)))
        ids = [n.id for n in nodes]
        edges = list(await db.scalars(select(GraphRelationship).where(GraphRelationship.workspace_id == workspace_id, GraphRelationship.source_id.in_(ids), GraphRelationship.target_id.in_(ids)).limit(3000)))
        workspace = await db.get(Workspace, workspace_id)
        return {"nodes": [{"id": n.id, "label": n.label, "kind": n.kind, "properties": n.properties} for n in nodes],
                "edges": [{"id": e.id, "source": e.source_id, "target": e.target_id, "kind": e.kind, "evidence": e.evidence} for e in edges],
                "projection": workspace.settings.get("graph_projection", {"status": "not_built", "source": "postgresql"}), "limits": {"documents": 300, "chunks_per_document": 100, "nodes": 1000, "edges": 3000}}


async def related_documents(workspace_id, query, seed_ids):
    graph = await graph_snapshot(workspace_id)
    terms = set(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,100}", query.lower()))
    matched = {n["id"] for n in graph["nodes"] if n["properties"].get("document_id") in seed_ids or terms.intersection(re.findall(r"[a-z0-9][a-z0-9_.\-/]{2,100}", n["label"].lower()))}
    reached = set(matched)
    for _ in range(2):
        frontier = set(reached)
        reached.update(x for e in graph["edges"] if e["source"] in frontier or e["target"] in frontier for x in (e["source"], e["target"]))
    settings = get_settings()
    if settings.neo4j_uri and graph["projection"]["status"] == "synced":
        import asyncio
        from neo4j import AsyncGraphDatabase
        try:
            async with asyncio.timeout(5):
                async with AsyncGraphDatabase.driver(settings.neo4j_uri, auth=("neo4j", settings.neo4j_password), connection_timeout=2) as driver:
                    async with driver.session() as session:
                        result = await session.run("MATCH p=(n:CortexEntity {workspace_id:$wid})-[:RELATED*0..2]-(d:CortexEntity {workspace_id:$wid,kind:'document'}) WHERE n.id IN $ids AND all(x IN nodes(p) WHERE x.workspace_id=$wid) RETURN DISTINCT d.id AS id LIMIT 30", wid=workspace_id, ids=list(matched))
                        ids = {r["id"] async for r in result}
                        reached = ids.intersection(n["id"] for n in graph["nodes"])
        except Exception:
            pass  # Canonical bounded traversal remains available if projection is down.
    return [n["properties"]["document_id"] for n in graph["nodes"] if n["id"] in reached and n["kind"] == "document"][:30]

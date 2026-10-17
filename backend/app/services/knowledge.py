import asyncio
from pathlib import Path
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import Session, transaction
from app.models.entities import Document, DocumentChunk
from app.rag.parsing import chunk_sections, parse_file
from app.rag import retrieval


async def ingest_document(workspace_id: str, document_id: str):
    async with transaction() as db:
        document = await db.scalar(select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id).with_for_update())
        if document is None or document.status == "deleting":
            return {"skipped": True}
        document.status, document.error = "processing", None
        path, filename = Path(document.storage_path), document.filename
    sections = await asyncio.to_thread(parse_file, path, Path(filename).suffix.lower())
    settings = get_settings()
    chunks = chunk_sections(document_id, sections, settings.chunk_size, settings.chunk_overlap)
    if len(chunks) > 5000:
        raise ValueError("Document exceeds the 5,000-chunk processing limit")
    await asyncio.to_thread(retrieval.delete_vectors, workspace_id, document_id)
    await asyncio.to_thread(retrieval.index_chunks, workspace_id, document_id, filename, chunks)
    async with transaction() as db:
        document = await db.scalar(select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id).with_for_update())
        if document is None or document.status == "deleting":
            await asyncio.to_thread(retrieval.delete_vectors, workspace_id, document_id)
            return {"skipped": True}
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        db.add_all([DocumentChunk(workspace_id=workspace_id, document_id=document_id, **item) for item in chunks])
        document.status = "indexed"
        document.metadata_json = {**document.metadata_json, "chunk_count": len(chunks), "page_count": max(s.page for s in sections)}
    from app.services.graph import rebuild_graph
    await rebuild_graph(workspace_id)
    return {"document_id": document_id, "chunks": len(chunks), "status": "indexed"}


async def search_knowledge(workspace_id: str, query: str, limit=6, document_ids=None):
    candidates = await asyncio.to_thread(retrieval.hybrid_candidates, workspace_id, query, limit, document_ids)
    from app.services.graph import related_documents
    related = await related_documents(workspace_id, query, [c["payload"].get("document_id") for c in candidates])
    if document_ids:
        related = [d for d in related if d in document_ids]
    if related:
        extra = await asyncio.to_thread(retrieval.hybrid_candidates, workspace_id, query, limit, related)
        seen = {c["id"] for c in candidates}
        candidates.extend({**c, "graph_expanded": True} for c in extra if c["id"] not in seen)
    if not candidates:
        return []
    async with Session() as db:
        rows = (await db.execute(select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id).where(
            DocumentChunk.id.in_([c["id"] for c in candidates]), DocumentChunk.workspace_id == workspace_id,
            Document.workspace_id == workspace_id, Document.status == "indexed"))).all()
        canonical = {chunk.id: (chunk, doc) for chunk, doc in rows}
        evidence = []
        for candidate in candidates:
            if candidate["id"] not in canonical:
                continue
            chunk, doc = canonical[candidate["id"]]
            evidence.append({"id": chunk.id, "source": "knowledge", "title": doc.filename, "content": chunk.content,
                             "reference": {"document_id": doc.id, "chunk_id": chunk.id, "page": chunk.page, "section": chunk.section,
                                           "filename": doc.filename, "sha256": doc.sha256}, "score": candidate["score"]})
            evidence[-1]["reference"]["graph_expanded"] = candidate.get("graph_expanded", False)
    ranked = await asyncio.to_thread(retrieval.rerank, query, evidence, limit)
    # A query with no plausible match should not acquire relevance merely because
    # every available chunk was ranked. This logit threshold needs calibration
    # for the configured cross-encoder/corpus; it is not a probability estimate.
    return ranked if ranked and ranked[0]["score"] >= get_settings().retrieval_min_score else []


async def delete_document(workspace_id, document_id):
    await asyncio.to_thread(retrieval.delete_vectors, workspace_id, document_id)
    async with transaction() as db:
        document = await db.scalar(select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id).with_for_update())
        if document:
            path = Path(document.storage_path).resolve()
            if not path.is_relative_to(get_settings().upload_dir.resolve()):
                raise ValueError("Refusing deletion outside the configured upload directory")
            path.unlink(missing_ok=True)
            await db.delete(document)
    from app.services.graph import rebuild_graph
    await rebuild_graph(workspace_id)
    return {"deleted": document_id}

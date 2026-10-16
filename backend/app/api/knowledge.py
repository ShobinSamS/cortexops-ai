import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import Principal, current_principal, require_role
from app.models.entities import Document, DocumentChunk, BackgroundJob
from app.rag.parsing import validate_file
from app.schemas.contracts import SearchRequest
from app.services.common import audit, owned, serialize
from app.services.jobs import enqueue

router = APIRouter()


@router.get("/documents")
async def documents(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    return [serialize(d, exclude=("storage_path",)) for d in await db.scalars(select(Document).where(Document.workspace_id == p.workspace_id).order_by(Document.created_at.desc()).limit(200))]


@router.post("/documents", status_code=202)
async def upload(file: UploadFile = File(...), p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    filename = Path((file.filename or "document.txt").replace("\\", "/")).name[:255]
    extension = Path(filename).suffix.lower()
    if extension not in {".txt", ".md", ".pdf", ".docx"}:
        raise HTTPException(400, "Allowed file types: PDF, TXT, Markdown and DOCX")
    directory = settings.upload_dir / p.workspace_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4()}{extension}"
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("wb") as target:
            while block := await file.read(64 * 1024):
                size += len(block)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "File exceeds the 20 MB upload limit")
                digest.update(block)
                await asyncio.to_thread(target.write, block)
        if size == 0:
            raise HTTPException(400, "Empty files are not accepted")
        try:
            await asyncio.to_thread(validate_file, path, extension)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        existing = await db.scalar(select(Document).where(Document.workspace_id == p.workspace_id, Document.sha256 == digest.hexdigest()))
        if existing:
            path.unlink(missing_ok=True)
            return {"document": serialize(existing, exclude=("storage_path",)), "duplicate": True}
        document = Document(workspace_id=p.workspace_id, uploaded_by=p.user_id, filename=filename,
                            content_type=file.content_type or "application/octet-stream", sha256=digest.hexdigest(), storage_path=str(path), size_bytes=size)
        db.add(document)
        await db.flush()
        audit(db, p, "document.upload", "document", document.id, {"filename": filename, "size_bytes": size})
        job = await enqueue(db, p, "ingest", {"document_id": document.id})
        return {"document": serialize(document, exclude=("storage_path",)), "job_id": job.id, "duplicate": False}
    except BaseException:
        # If the record committed before queue failure, preserve its source for retry.
        if "document" not in locals() or document.id is None:
            path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/documents/{document_id}")
async def document(document_id: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    return serialize(await owned(db, Document, document_id, p), exclude=("storage_path",))


@router.get("/documents/{document_id}/chunks")
async def chunks(document_id: str, limit: int = 50, offset: int = 0, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    await owned(db, Document, document_id, p)
    return [serialize(x) for x in await db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id, DocumentChunk.workspace_id == p.workspace_id).order_by(DocumentChunk.position).offset(max(0, offset)).limit(min(100, max(1, limit))))]


@router.post("/documents/{document_id}/reindex", status_code=202)
async def reindex(document_id: str, p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db)):
    item = await owned(db, Document, document_id, p, lock=True)
    if item.status in {"processing", "queued", "deleting"}:
        raise HTTPException(409, "Document already has a pending operation")
    item.status = "queued"
    audit(db, p, "document.reindex", "document", item.id)
    job = await enqueue(db, p, "ingest", {"document_id": item.id})
    return {"job_id": job.id}


@router.delete("/documents/{document_id}", status_code=202)
async def delete_document(document_id: str, p: Principal = Depends(require_role("analyst")), db: AsyncSession = Depends(get_db)):
    item = await owned(db, Document, document_id, p, lock=True)
    item.status = "deleting"
    audit(db, p, "document.delete", "document", item.id)
    job = await enqueue(db, p, "delete_document", {"document_id": item.id})
    return {"job_id": job.id}


@router.post("/knowledge/search", status_code=202)
async def search(data: SearchRequest, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    job = await enqueue(db, p, "search", {"query": data.query, "limit": data.limit, "document_ids": data.document_ids})
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def job(job_id: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    item = await owned(db, BackgroundJob, job_id, p)
    result = serialize(item, exclude=("payload",))
    if item.kind == "search" and item.status == "completed":
        evidence = item.result.get("evidence", [])
        valid = set(await db.scalars(select(DocumentChunk.id).join(Document, Document.id == DocumentChunk.document_id).where(
            DocumentChunk.id.in_([e["id"] for e in evidence]), DocumentChunk.workspace_id == p.workspace_id, Document.status == "indexed")))
        result["result"] = {"evidence": [e for e in evidence if e["id"] in valid]}
    return result

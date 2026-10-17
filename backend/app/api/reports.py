import asyncio
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, current_principal
from app.models.entities import Report
from app.services.common import owned, serialize

router = APIRouter()


@router.get("/reports")
async def reports(p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return [serialize(x, exclude=("content", "markdown")) for x in await db.scalars(select(Report).where(Report.workspace_id == p.workspace_id).order_by(Report.created_at.desc()).limit(100))]


@router.get("/reports/{report_id}")
async def report(report_id: str, p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    return serialize(await owned(db, Report, report_id, p))


@router.get("/reports/{report_id}/export")
async def export(report_id: str, format: str = "md", p: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db, scope="function")):
    item = await owned(db, Report, report_id, p)
    if format == "pdf":
        from app.services.pdf_report import report_pdf
        data = await asyncio.to_thread(report_pdf, item.title, item.id, item.content)
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="cortexops-{item.id}.pdf"'})
    if format != "md":
        raise HTTPException(400, "Choose a supported export format")
    return Response(item.markdown, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="cortexops-{item.id}.md"'})

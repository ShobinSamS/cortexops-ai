from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import Principal, require_role
from app.services.demo import seed

router = APIRouter()


@router.post("/demo/seed", status_code=202)
async def seed_demo(p: Principal = Depends(require_role("owner")), db: AsyncSession = Depends(get_db, scope="function")):
    return await seed(db, p)

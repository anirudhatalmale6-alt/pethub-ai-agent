from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import User
from app.models.knowledge import KnowledgeEntry
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class KnowledgeCreate(BaseModel):
    category: str
    key: str
    value: str


@router.get("/")
async def list_knowledge(
    category: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(KnowledgeEntry).order_by(KnowledgeEntry.category, KnowledgeEntry.key)
    if category:
        query = query.where(KnowledgeEntry.category == category)

    result = await db.execute(query)
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "category": e.category,
            "key": e.key,
            "value": e.value,
            "updated_at": e.updated_at.isoformat(),
        }
        for e in entries
    ]


@router.post("/")
async def create_knowledge(
    req: KnowledgeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.key == req.key, KnowledgeEntry.category == req.category)
    )
    entry = existing.scalar_one_or_none()

    if entry:
        entry.value = req.value
        action = "updated"
    else:
        entry = KnowledgeEntry(category=req.category, key=req.key, value=req.value, created_by=user.id)
        db.add(entry)
        action = "created"

    await db.commit()
    return {"status": action, "category": req.category, "key": req.key}


@router.delete("/{entry_id}")
async def delete_knowledge(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    await db.delete(entry)
    await db.commit()
    return {"deleted": True, "key": entry.key}

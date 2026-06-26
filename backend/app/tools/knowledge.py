import logging
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.knowledge import KnowledgeEntry
from app.tools.registry import registry

logger = logging.getLogger(__name__)


async def _get_db() -> AsyncSession:
    return async_session()


@registry.tool(
    name="remember",
    description="Store a piece of information that should persist across conversations. Use this to save user preferences, site details, brand guidelines, common instructions, or anything the user wants you to remember for future chats. Categories: preference, site_info, brand, workflow, note.",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category of knowledge",
                "enum": ["preference", "site_info", "brand", "workflow", "note"],
            },
            "key": {"type": "string", "description": "Short descriptive key (e.g. 'writing_style', 'brand_colour', 'target_audience')"},
            "value": {"type": "string", "description": "The information to remember"},
        },
        "required": ["category", "key", "value"],
    },
    category="system",
)
async def remember(category: str = "", key: str = "", value: str = "") -> dict:
    async with async_session() as db:
        existing = await db.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.key == key, KnowledgeEntry.category == category)
        )
        entry = existing.scalar_one_or_none()

        if entry:
            entry.value = value
            action = "updated"
        else:
            entry = KnowledgeEntry(category=category, key=key, value=value)
            db.add(entry)
            action = "stored"

        await db.commit()
        return {"status": action, "category": category, "key": key, "value": value}


@registry.tool(
    name="recall",
    description="Retrieve stored knowledge. Use this at the start of tasks to check for user preferences, site details, or previously saved information.",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category to search (leave empty for all)",
                "enum": ["preference", "site_info", "brand", "workflow", "note", ""],
            },
            "key": {"type": "string", "description": "Specific key to look up (leave empty to list all in category)", "default": ""},
        },
    },
    category="system",
)
async def recall(category: str = "", key: str = "") -> dict:
    async with async_session() as db:
        query = select(KnowledgeEntry)
        if category:
            query = query.where(KnowledgeEntry.category == category)
        if key:
            query = query.where(KnowledgeEntry.key == key)
        query = query.order_by(KnowledgeEntry.category, KnowledgeEntry.key)

        result = await db.execute(query)
        entries = result.scalars().all()

        if not entries:
            return {"count": 0, "entries": [], "message": "No stored knowledge found for this query."}

        return {
            "count": len(entries),
            "entries": [
                {"category": e.category, "key": e.key, "value": e.value, "updated": e.updated_at.isoformat()}
                for e in entries
            ],
        }


@registry.tool(
    name="forget",
    description="Remove a previously stored piece of knowledge.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The key of the knowledge entry to remove"},
            "category": {"type": "string", "description": "Category of the entry", "default": ""},
        },
        "required": ["key"],
    },
    category="system",
)
async def forget(key: str = "", category: str = "") -> dict:
    async with async_session() as db:
        query = delete(KnowledgeEntry).where(KnowledgeEntry.key == key)
        if category:
            query = query.where(KnowledgeEntry.category == category)
        result = await db.execute(query)
        await db.commit()
        return {"deleted": result.rowcount, "key": key}

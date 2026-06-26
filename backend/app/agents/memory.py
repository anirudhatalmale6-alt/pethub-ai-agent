import json
import logging
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session
from app.models.knowledge import KnowledgeEntry, ConversationMemory
from app.models.models import Message, Conversation

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """Analyse this conversation and extract important information to remember for future conversations.

Return a JSON object with:
{
  "summary": "2-3 sentence summary of what was discussed and accomplished",
  "learnings": ["list of new facts, preferences, or decisions the user revealed"],
  "corrections": ["list of things the user corrected or said they don't want"],
  "topics": ["list of topic keywords discussed (e.g. 'seo', 'dog content', 'page layout')"],
  "auto_remember": [
    {"category": "preference|site_info|brand|workflow|note", "key": "short_key", "value": "what to remember"}
  ]
}

Rules for auto_remember:
- Only include things that should apply to ALL future conversations
- User preferences ("I prefer...", "always...", "never...", "from now on...")
- Corrections ("don't do X", "not like that, do it this way")
- Important decisions that affect future work
- Do NOT include one-time task details or things already stored
- Keep keys short and descriptive

If nothing worth remembering, return empty arrays."""

RELEVANCE_PROMPT = """Given the user's current message, which of these stored memories are relevant? Return ONLY the relevant ones.

User message: {message}

Stored memories:
{memories}

Return a JSON array of the relevant memory keys. If none are relevant, return [].
Only include memories that would actually help answer or execute the user's current request."""


class MemoryEngine:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def extract_and_store(self, conversation_id: str) -> dict[str, Any]:
        async with async_session() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.role.in_(["user", "assistant"]))
                .order_by(Message.created_at)
            )
            messages = result.scalars().all()

            if len(messages) < 2:
                return {"skipped": True, "reason": "Too few messages"}

            existing = await db.execute(
                select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
            )
            if existing.scalar_one_or_none():
                return {"skipped": True, "reason": "Already processed"}

            conversation_text = "\n".join(
                f"{m.role.upper()}: {m.content}" for m in messages if m.content
            )

            if len(conversation_text) < 50:
                return {"skipped": True, "reason": "Too short"}

            try:
                response = await self.client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=[
                        {"role": "system", "content": EXTRACT_PROMPT},
                        {"role": "user", "content": conversation_text[:8000]},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )

                data = json.loads(response.choices[0].message.content or "{}")
            except Exception as e:
                logger.exception("Memory extraction failed")
                return {"error": str(e)}

            memory = ConversationMemory(
                conversation_id=conversation_id,
                summary=data.get("summary", ""),
                learnings=data.get("learnings", []),
                corrections=data.get("corrections", []),
                topics=data.get("topics", []),
                message_count=len(messages),
            )
            db.add(memory)

            auto_items = data.get("auto_remember", [])
            stored_count = 0
            for item in auto_items:
                cat = item.get("category", "note")
                key = item.get("key", "")
                value = item.get("value", "")
                if not key or not value:
                    continue

                existing_entry = await db.execute(
                    select(KnowledgeEntry).where(KnowledgeEntry.key == key, KnowledgeEntry.category == cat)
                )
                entry = existing_entry.scalar_one_or_none()
                if entry:
                    entry.value = value
                else:
                    db.add(KnowledgeEntry(category=cat, key=key, value=value))
                stored_count += 1

            await db.commit()

            return {
                "summary": data.get("summary", ""),
                "learnings": len(data.get("learnings", [])),
                "corrections": len(data.get("corrections", [])),
                "auto_remembered": stored_count,
            }

    async def get_relevant_context(self, user_message: str) -> str:
        async with async_session() as db:
            result = await db.execute(
                select(KnowledgeEntry).order_by(KnowledgeEntry.category, KnowledgeEntry.key)
            )
            entries = result.scalars().all()

            if not entries:
                return ""

            mem_result = await db.execute(
                select(ConversationMemory).order_by(ConversationMemory.created_at.desc()).limit(10)
            )
            recent_memories = mem_result.scalars().all()

        context_parts = []

        if entries:
            context_parts.append("STORED KNOWLEDGE (apply these automatically):")
            for e in entries:
                context_parts.append(f"- [{e.category}] {e.key}: {e.value}")

        if recent_memories:
            context_parts.append("\nRECENT CONVERSATION HISTORY:")
            for m in recent_memories[:5]:
                parts = [f"- {m.summary}"]
                if m.corrections:
                    parts.append(f"  Corrections: {'; '.join(m.corrections[:3])}")
                context_parts.append("\n".join(parts))

        return "\n".join(context_parts)


memory_engine = MemoryEngine()

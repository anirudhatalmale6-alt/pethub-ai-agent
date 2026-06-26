import json
import logging
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select, func

from app.config import get_settings
from app.database import async_session
from app.models.feedback import PerformanceRecord, ImprovementRule

logger = logging.getLogger(__name__)

EVALUATE_PROMPT = """You are a performance evaluation engine. Analyse the action and its result, then score it and extract learnings.

Action type: {action_type}
Action detail: {action_detail}
Result: {result}

Return a JSON object:
{{
  "scores": {{
    "completion": 0-100,
    "quality": 0-100,
    "efficiency": 0-100
  }},
  "overall_score": 0-100,
  "what_worked": ["list of things that went well"],
  "what_failed": ["list of things that failed or could be better"],
  "improvements": ["specific actionable improvements for next time - be concrete"]
}}

Scoring guide:
- completion: Did the action fully achieve its goal? 100 = fully complete, 0 = total failure
- quality: How good is the output? Consider accuracy, formatting, best practices
- efficiency: Was this done optimally? Could it have been done faster or with fewer steps?

For improvements, be very specific. Instead of "do better SEO", say "include alt text on all images and keep meta descriptions between 120-155 characters"."""

CONTENT_EVALUATE_PROMPT = """You are a content quality evaluator. Score this WordPress content.

Title: {title}
Content (first 3000 chars): {content}

Return a JSON object:
{{
  "scores": {{
    "seo_readiness": 0-100,
    "readability": 0-100,
    "structure": 0-100,
    "completeness": 0-100,
    "engagement": 0-100
  }},
  "overall_score": 0-100,
  "what_worked": ["positive aspects"],
  "what_failed": ["missing or weak elements"],
  "improvements": ["specific improvements for future content creation"]
}}

Evaluate based on:
- seo_readiness: Does it have H2s, proper keyword usage, meta-friendly structure, FAQ section?
- readability: Is it clear, well-written, appropriate for UK pet owners?
- structure: Proper heading hierarchy, paragraphs, lists, tables?
- completeness: Does it cover the topic thoroughly? Sources, FAQs, comparison tables?
- engagement: Would readers find this useful? Does it have CTAs, internal links?"""


class FeedbackEngine:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def evaluate_action(self, action_type: str, action_detail: str,
                               result: Any, conversation_id: str = "") -> dict:
        result_str = json.dumps(result)[:4000] if isinstance(result, dict) else str(result)[:4000]

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": EVALUATE_PROMPT.format(
                        action_type=action_type, action_detail=action_detail, result=result_str
                    )},
                    {"role": "user", "content": "Evaluate this action and its result."},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            data = json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            logger.exception("Feedback evaluation failed")
            return {"error": str(e)}

        async with async_session() as db:
            record = PerformanceRecord(
                conversation_id=conversation_id or None,
                action_type=action_type,
                action_detail=action_detail[:255],
                scores=data.get("scores", {}),
                overall_score=data.get("overall_score", 0),
                what_worked=data.get("what_worked", []),
                what_failed=data.get("what_failed", []),
                improvements=data.get("improvements", []),
                context={"result_preview": result_str[:500]},
            )
            db.add(record)

            for improvement in data.get("improvements", []):
                existing = await db.execute(
                    select(ImprovementRule).where(
                        ImprovementRule.action_type == action_type,
                        ImprovementRule.rule == improvement,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(ImprovementRule(
                        action_type=action_type,
                        rule=improvement,
                        source_record_id=record.id,
                    ))

            await db.commit()

        return data

    async def evaluate_content(self, title: str, content: str, conversation_id: str = "") -> dict:
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": CONTENT_EVALUATE_PROMPT.format(
                        title=title, content=content[:3000]
                    )},
                    {"role": "user", "content": "Score this content."},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            data = json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            logger.exception("Content evaluation failed")
            return {"error": str(e)}

        async with async_session() as db:
            record = PerformanceRecord(
                conversation_id=conversation_id or None,
                action_type="content_creation",
                action_detail=title[:255],
                scores=data.get("scores", {}),
                overall_score=data.get("overall_score", 0),
                what_worked=data.get("what_worked", []),
                what_failed=data.get("what_failed", []),
                improvements=data.get("improvements", []),
            )
            db.add(record)

            for improvement in data.get("improvements", []):
                existing = await db.execute(
                    select(ImprovementRule).where(
                        ImprovementRule.action_type == "content_creation",
                        ImprovementRule.rule == improvement,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(ImprovementRule(
                        action_type="content_creation",
                        rule=improvement,
                        source_record_id=record.id,
                    ))

            await db.commit()

        return data

    async def get_improvement_rules(self, action_type: str = "") -> list[str]:
        async with async_session() as db:
            query = select(ImprovementRule).order_by(ImprovementRule.times_applied.desc())
            if action_type:
                query = query.where(ImprovementRule.action_type == action_type)
            result = await db.execute(query.limit(20))
            rules = result.scalars().all()
            return [r.rule for r in rules]

    async def get_performance_summary(self, action_type: str = "", days: int = 30) -> dict:
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(days=days)

        async with async_session() as db:
            query = select(PerformanceRecord).where(PerformanceRecord.created_at >= since)
            if action_type:
                query = query.where(PerformanceRecord.action_type == action_type)
            result = await db.execute(query.order_by(PerformanceRecord.created_at.desc()).limit(50))
            records = result.scalars().all()

            if not records:
                return {"count": 0, "avg_score": 0, "trend": "no data"}

            scores = [r.overall_score for r in records]
            avg = sum(scores) / len(scores)

            recent_avg = sum(scores[:5]) / min(len(scores), 5) if scores else 0
            older_avg = sum(scores[5:10]) / min(len(scores[5:]), 5) if len(scores) > 5 else recent_avg
            trend = "improving" if recent_avg > older_avg + 2 else ("declining" if recent_avg < older_avg - 2 else "stable")

            all_failures = []
            for r in records[:10]:
                all_failures.extend(r.what_failed or [])

            from collections import Counter
            common_issues = Counter(all_failures).most_common(5)

            return {
                "count": len(records),
                "avg_score": round(avg, 1),
                "recent_avg": round(recent_avg, 1),
                "trend": trend,
                "score_range": {"min": round(min(scores), 1), "max": round(max(scores), 1)},
                "common_issues": [{"issue": issue, "frequency": count} for issue, count in common_issues],
            }


feedback_engine = FeedbackEngine()

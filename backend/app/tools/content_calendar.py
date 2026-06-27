import json
import logging
import os
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

CALENDAR_FILE = os.environ.get("CALENDAR_FILE", "/app/config/content_calendar.json")


@registry.tool(
    name="plan_content_calendar",
    description="Generate a content calendar with article topics, keywords, and scheduling. Plans weeks of content based on your site's gaps and target audience.",
    parameters={
        "type": "object",
        "properties": {
            "weeks": {"type": "integer", "description": "Number of weeks to plan", "default": 4},
            "posts_per_week": {"type": "integer", "description": "Articles per week", "default": 3},
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Categories to cover (e.g. ['dogs', 'cats', 'fish'])",
            },
        },
    },
    category="content",
)
async def plan_content_calendar(weeks: int = 4, posts_per_week: int = 3,
                                 categories: list[str] | None = None) -> dict:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    workspace_context = ""
    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        if ws:
            workspace_context = f"Site: {ws.domain}\nRules: {', '.join(ws.content_rules[:5])}"
    except Exception:
        pass

    cats = categories or ["dogs", "cats", "fish", "small pets"]

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": f"""Create a content calendar for a UK pet supplies website.
{workspace_context}

Return JSON:
{{
    "calendar": [
        {{
            "week": 1,
            "articles": [
                {{
                    "day": "Monday",
                    "title": "Article title",
                    "focus_keyword": "target keyword",
                    "category": "dogs|cats|fish|small_pets",
                    "type": "guide|comparison|how_to|listicle",
                    "estimated_words": 2000,
                    "internal_link_targets": ["related page slugs"],
                    "notes": "brief content direction"
                }}
            ]
        }}
    ],
    "strategy_notes": "overall content strategy explanation"
}}

Cover categories: {', '.join(cats)}
Target UK keywords. Mix article types. Build topical authority."""},
            {"role": "user", "content": f"Plan {weeks} weeks with {posts_per_week} articles per week."},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )

    calendar = json.loads(response.choices[0].message.content or "{}")

    with open(CALENDAR_FILE, "w") as f:
        json.dump({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "calendar": calendar,
        }, f, indent=2)

    total_articles = sum(len(w.get("articles", [])) for w in calendar.get("calendar", []))

    return {
        "weeks_planned": weeks,
        "total_articles": total_articles,
        "calendar": calendar.get("calendar", []),
        "strategy": calendar.get("strategy_notes", ""),
        "saved_to": CALENDAR_FILE,
    }


@registry.tool(
    name="get_content_calendar",
    description="Retrieve the current content calendar.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="content",
)
async def get_content_calendar() -> dict:
    if not os.path.exists(CALENDAR_FILE):
        return {"error": "No content calendar found. Use plan_content_calendar to create one."}

    with open(CALENDAR_FILE) as f:
        data = json.load(f)

    return data

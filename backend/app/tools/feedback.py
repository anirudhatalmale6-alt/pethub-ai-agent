import logging

from app.tools.registry import registry
from app.agents.feedback import feedback_engine

logger = logging.getLogger(__name__)


@registry.tool(
    name="evaluate_content",
    description="Score a piece of content for quality. Returns SEO readiness, readability, structure, completeness, and engagement scores. Use after creating or updating content to check quality.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "WordPress post/page ID to evaluate"},
        },
        "required": ["post_id"],
    },
    category="system",
)
async def evaluate_content(post_id: int = 0) -> dict:
    from app.tools.wordpress import _detect_post_type, _wp_request
    post_type = await _detect_post_type("", "", "", post_id)
    result = await _wp_request("GET", "", "", "", f"wp/v2/{post_type}/{post_id}")

    title = result.get("title", {}).get("rendered", "")
    content = result.get("content", {}).get("rendered", "")

    evaluation = await feedback_engine.evaluate_content(title, content)
    return {"post_id": post_id, "title": title, **evaluation}


@registry.tool(
    name="get_improvement_tips",
    description="Get learned improvement tips from past performance evaluations. Shows what the system has learned to do better over time.",
    parameters={
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "description": "Type of action to get tips for",
                "default": "",
                "enum": ["content_creation", "wp_create_post", "wp_update_post", "seo_audit", ""],
            },
        },
    },
    category="system",
)
async def get_improvement_tips(action_type: str = "") -> dict:
    rules = await feedback_engine.get_improvement_rules(action_type)
    summary = await feedback_engine.get_performance_summary(action_type)

    return {
        "improvement_rules": rules,
        "performance_summary": summary,
    }


@registry.tool(
    name="performance_report",
    description="Get a performance report showing scores, trends, and common issues over time.",
    parameters={
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "Number of days to report on", "default": 30},
        },
    },
    category="system",
)
async def performance_report(days: int = 30) -> dict:
    overall = await feedback_engine.get_performance_summary("", days)
    content = await feedback_engine.get_performance_summary("content_creation", days)
    wp = await feedback_engine.get_performance_summary("wp_create_post", days)

    return {
        "period_days": days,
        "overall": overall,
        "content_creation": content,
        "wordpress_operations": wp,
    }

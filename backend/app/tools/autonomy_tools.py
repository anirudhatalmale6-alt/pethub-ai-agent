import logging

from app.tools.registry import registry
from app.agents.autonomy import autonomy

logger = logging.getLogger(__name__)


@registry.tool(
    name="set_autonomy_level",
    description="Set the agent's autonomy level. Level 1: Suggest only (never executes). Level 2: Approval required for writes (default). Level 3: Smart auto (low-risk actions auto-execute). Level 4: Full auto (only destructive actions need approval).",
    parameters={
        "type": "object",
        "properties": {
            "level": {
                "type": "integer",
                "description": "Autonomy level (1-4)",
                "enum": [1, 2, 3, 4],
            },
        },
        "required": ["level"],
    },
    category="system",
)
async def set_autonomy_level(level: int = 2) -> dict:
    result = autonomy.set_level(level)
    if "error" in result:
        return result
    status = autonomy.get_status()
    return {
        **result,
        "auto_execute_count": status["auto_execute_count"],
        "approval_required_count": status["approval_required_count"],
    }


@registry.tool(
    name="get_autonomy_status",
    description="Check the current autonomy level and see which tools auto-execute vs need approval.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="system",
)
async def get_autonomy_status() -> dict:
    return autonomy.get_status()

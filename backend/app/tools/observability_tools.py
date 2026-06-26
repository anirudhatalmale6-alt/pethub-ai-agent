import logging

from app.tools.registry import registry
from app.agents.observability import observability

logger = logging.getLogger(__name__)


@registry.tool(
    name="system_intelligence",
    description="Get comprehensive system intelligence: activity stats, cost estimates, tool health, reliability warnings, and optimisation recommendations. Use this to understand how the system is performing.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="system",
)
async def system_intelligence() -> dict:
    return await observability.get_system_intelligence()


@registry.tool(
    name="tool_health_check",
    description="Check the health and reliability of all tools. Shows which tools are failing, which are slow, and recommends alternatives.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="system",
)
async def tool_health_check() -> dict:
    health = observability.tracker.get_tool_health()
    unreliable = observability.tracker.get_unreliable_tools()
    slow = observability.tracker.get_slow_tools()

    return {
        "total_tools_tracked": len(health),
        "unreliable_tools": unreliable,
        "slow_tools": slow,
        "per_tool": {
            tool: {
                "reliability": h["reliability"],
                "avg_response_ms": h.get("avg_ms", 0),
                "calls_24h": h["calls"],
                "failures": h["failures"],
                "recent_errors": h.get("recent_errors", []),
            }
            for tool, h in sorted(health.items(), key=lambda x: x[1]["reliability"])
        },
    }

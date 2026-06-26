import logging

from app.tools.registry import registry
from app.agents.goal_runner import goal_runner

logger = logging.getLogger(__name__)


@registry.tool(
    name="set_goal",
    description="Set an autonomous goal for the agent to work on continuously. The agent will run scheduled tasks to analyse and monitor progress towards the goal. Safe read-only operations run automatically, any changes need approval.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short goal name (e.g. 'seo_improvement')"},
            "description": {"type": "string", "description": "Detailed goal description (e.g. 'Improve SEO scores across all pages to above 80/100 by finding and fixing missing meta descriptions, alt text, and heading structure')"},
            "schedule": {"type": "string", "description": "How often to run", "default": "daily", "enum": ["hourly", "daily", "weekly"]},
        },
        "required": ["name", "description"],
    },
    category="goals",
)
async def set_goal(name: str = "", description: str = "", schedule: str = "daily") -> dict:
    goal = goal_runner.add_goal(name, description, schedule)
    return {
        "status": "created",
        "goal_id": goal["id"],
        "name": name,
        "schedule": schedule,
        "message": f"Goal '{name}' set to run {schedule}. The agent will autonomously analyse and report progress.",
    }


@registry.tool(
    name="list_goals",
    description="List all autonomous goals and their current status.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="goals",
)
async def list_goals() -> dict:
    goals = goal_runner.list_goals()
    return {
        "count": len(goals),
        "goals": [
            {
                "id": g["id"],
                "name": g["name"],
                "description": g["description"][:100],
                "schedule": g["schedule"],
                "enabled": g["enabled"],
                "run_count": g.get("run_count", 0),
                "last_run": g.get("last_run"),
            }
            for g in goals
        ],
    }


@registry.tool(
    name="run_goal_now",
    description="Manually trigger an autonomous goal to run immediately instead of waiting for the schedule.",
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal ID to run"},
        },
        "required": ["goal_id"],
    },
    category="goals",
)
async def run_goal_now(goal_id: str = "") -> dict:
    goals = goal_runner.list_goals()
    goal = next((g for g in goals if g["id"] == goal_id), None)
    if not goal:
        return {"error": f"Goal '{goal_id}' not found"}

    result = await goal_runner.run_goal(goal)
    return result


@registry.tool(
    name="get_goal_digest",
    description="Get the latest digest/report from an autonomous goal's last run.",
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal ID"},
        },
        "required": ["goal_id"],
    },
    category="goals",
)
async def get_goal_digest(goal_id: str = "") -> dict:
    goals = goal_runner.list_goals()
    goal = next((g for g in goals if g["id"] == goal_id), None)
    if not goal:
        return {"error": f"Goal '{goal_id}' not found"}

    return {
        "goal": goal["name"],
        "last_run": goal.get("last_run"),
        "run_count": goal.get("run_count", 0),
        "digest": goal.get("last_digest", {"message": "No runs completed yet"}),
    }


@registry.tool(
    name="toggle_goal",
    description="Enable or disable an autonomous goal.",
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal ID"},
            "enabled": {"type": "boolean", "description": "True to enable, False to disable"},
        },
        "required": ["goal_id", "enabled"],
    },
    category="goals",
)
async def toggle_goal(goal_id: str = "", enabled: bool = True) -> dict:
    result = goal_runner.toggle_goal(goal_id, enabled)
    if not result:
        return {"error": f"Goal '{goal_id}' not found"}
    return {"goal": result["name"], "enabled": enabled, "status": "enabled" if enabled else "disabled"}


@registry.tool(
    name="remove_goal",
    description="Remove an autonomous goal permanently.",
    parameters={
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Goal ID to remove"},
        },
        "required": ["goal_id"],
    },
    category="goals",
    requires_approval=True,
)
async def remove_goal(goal_id: str = "") -> dict:
    removed = goal_runner.remove_goal(goal_id)
    return {"removed": removed, "goal_id": goal_id}

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.tools.registry import registry

logger = logging.getLogger(__name__)

GOALS_FILE = os.environ.get("GOALS_FILE", "/app/goals.json")

PLAN_PROMPT = """You are an autonomous goal-oriented agent. Given a goal, create a list of safe, read-only analysis tasks to work towards it.

Goal: {goal}
Available tools: {tools}
Last run results: {last_results}

Rules:
- ONLY use read-only tools (list, get, audit, check, search, analyse, evaluate, recall)
- NEVER use tools that create, update, delete, or modify anything
- Focus on gathering data, finding issues, and generating recommendations
- Be specific about which tools to call and with what arguments

Return JSON:
{{
    "tasks": [
        {{
            "description": "what this task does",
            "tool": "tool_name",
            "arguments": {{...}},
            "reason": "how this helps achieve the goal"
        }}
    ],
    "max_tasks": 5
}}"""

SUMMARISE_PROMPT = """Summarise these autonomous task results into a clear, actionable daily digest.

Goal: {goal}
Results: {results}

Return JSON:
{{
    "summary": "2-3 sentence overview",
    "findings": ["key finding 1", "key finding 2", ...],
    "recommendations": [
        {{"action": "what to do", "priority": "high|medium|low", "reason": "why"}}
    ],
    "metrics": {{
        "pages_checked": 0,
        "issues_found": 0,
        "score_average": 0
    }}
}}"""

SAFE_TOOLS = {
    "wp_list_posts", "wp_list_pages", "wp_get_post", "wp_list_categories",
    "wp_get_seo_meta", "seo_audit_page", "check_page_speed", "check_broken_links",
    "screenshot_and_analyse", "ml_list_subscribers", "ml_list_campaigns",
    "ml_subscriber_stats", "ml_list_groups", "amazon_search",
    "recall", "get_improvement_tips", "performance_report",
    "evaluate_content", "check_job_status", "list_connectors", "list_projects",
    "crawl_site", "site_health_audit", "get_site_urls", "visual_site_check",
    "list_workspaces", "get_autonomy_status", "system_intelligence", "tool_health_check",
}


class GoalRunner:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self._running = False
        self._goals: list[dict] = []
        self._load_goals()

    def _load_goals(self):
        if os.path.exists(GOALS_FILE):
            with open(GOALS_FILE) as f:
                self._goals = json.load(f)
        else:
            self._goals = []

    def _save_goals(self):
        with open(GOALS_FILE, "w") as f:
            json.dump(self._goals, f, indent=2, default=str)

    def add_goal(self, name: str, description: str, schedule: str = "daily",
                 enabled: bool = True) -> dict:
        goal = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "description": description,
            "schedule": schedule,
            "enabled": enabled,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_run": None,
            "last_digest": None,
            "run_count": 0,
        }
        self._goals.append(goal)
        self._save_goals()
        return goal

    def remove_goal(self, goal_id: str) -> bool:
        before = len(self._goals)
        self._goals = [g for g in self._goals if g["id"] != goal_id]
        self._save_goals()
        return len(self._goals) < before

    def list_goals(self) -> list[dict]:
        self._load_goals()
        return self._goals

    def toggle_goal(self, goal_id: str, enabled: bool) -> dict | None:
        for g in self._goals:
            if g["id"] == goal_id:
                g["enabled"] = enabled
                self._save_goals()
                return g
        return None

    async def run_goal(self, goal: dict) -> dict:
        safe_tools = [t for t in registry.list_tools() if t.name in SAFE_TOOLS]
        tools_desc = "\n".join(f"- {t.name}: {t.description[:80]}" for t in safe_tools)

        last_results = goal.get("last_digest", "No previous run")

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": PLAN_PROMPT.format(
                        goal=goal["description"],
                        tools=tools_desc,
                        last_results=str(last_results)[:1000],
                    )},
                    {"role": "user", "content": "Plan the next autonomous run."},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            plan = json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            return {"error": f"Planning failed: {e}"}

        tasks = plan.get("tasks", [])[:5]
        results = []

        for task in tasks:
            tool_name = task.get("tool", "")
            arguments = task.get("arguments", {})

            if tool_name not in SAFE_TOOLS:
                results.append({
                    "task": task.get("description", ""),
                    "status": "blocked",
                    "reason": f"Tool '{tool_name}' is not in the safe list",
                })
                continue

            try:
                result = await registry.execute(tool_name, arguments)
                results.append({
                    "task": task.get("description", ""),
                    "tool": tool_name,
                    "status": "completed",
                    "result": result if isinstance(result, dict) else {"output": str(result)[:500]},
                })
            except Exception as e:
                results.append({
                    "task": task.get("description", ""),
                    "tool": tool_name,
                    "status": "failed",
                    "error": str(e)[:200],
                })

        try:
            digest_resp = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": SUMMARISE_PROMPT.format(
                        goal=goal["description"],
                        results=json.dumps(results)[:4000],
                    )},
                    {"role": "user", "content": "Create the digest."},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            digest = json.loads(digest_resp.choices[0].message.content or "{}")
        except Exception:
            digest = {"summary": "Run completed but digest generation failed", "findings": [], "recommendations": []}

        goal["last_run"] = datetime.now(timezone.utc).isoformat()
        goal["last_digest"] = digest
        goal["run_count"] = goal.get("run_count", 0) + 1
        self._save_goals()

        return {
            "goal": goal["name"],
            "tasks_executed": len(results),
            "succeeded": sum(1 for r in results if r["status"] == "completed"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "blocked": sum(1 for r in results if r["status"] == "blocked"),
            "digest": digest,
        }

    async def run_scheduled(self):
        self._running = True
        logger.info("Goal runner started")

        while self._running:
            try:
                self._load_goals()
                now = datetime.now(timezone.utc)

                for goal in self._goals:
                    if not goal.get("enabled", True):
                        continue

                    schedule = goal.get("schedule", "daily")
                    last_run = goal.get("last_run")

                    should_run = False
                    if not last_run:
                        should_run = True
                    else:
                        last = datetime.fromisoformat(last_run)
                        if schedule == "hourly":
                            should_run = (now - last).total_seconds() >= 3600
                        elif schedule == "daily":
                            should_run = (now - last).total_seconds() >= 86400
                        elif schedule == "weekly":
                            should_run = (now - last).total_seconds() >= 604800

                    if should_run:
                        logger.info(f"Running goal: {goal['name']}")
                        try:
                            await self.run_goal(goal)
                        except Exception:
                            logger.exception(f"Goal run failed: {goal['name']}")

            except Exception:
                logger.exception("Goal runner cycle error")

            await asyncio.sleep(300)

    def stop(self):
        self._running = False


goal_runner = GoalRunner()

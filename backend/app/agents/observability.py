import json
import logging
import time
from collections import defaultdict
from typing import Any

from app.database import async_session
from app.models.models import ToolExecution, Message
from sqlalchemy import select, func, case
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class ToolTracker:
    def __init__(self):
        self._calls: list[dict] = []
        self._max_history = 500

    def record(self, tool_name: str, duration_ms: int, success: bool,
               error: str = "", arguments_size: int = 0, result_size: int = 0):
        self._calls.append({
            "tool": tool_name,
            "duration_ms": duration_ms,
            "success": success,
            "error": error[:200] if error else "",
            "args_size": arguments_size,
            "result_size": result_size,
            "time": time.time(),
        })
        if len(self._calls) > self._max_history:
            self._calls = self._calls[-self._max_history:]

    def get_tool_health(self) -> dict[str, dict]:
        health: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "calls": 0, "successes": 0, "failures": 0, "total_ms": 0,
            "recent_errors": [], "reliability": 100.0,
        })

        cutoff = time.time() - 86400
        recent = [c for c in self._calls if c["time"] > cutoff]

        for call in recent:
            h = health[call["tool"]]
            h["calls"] += 1
            h["total_ms"] += call["duration_ms"]
            if call["success"]:
                h["successes"] += 1
            else:
                h["failures"] += 1
                if call["error"]:
                    h["recent_errors"].append(call["error"])
                    h["recent_errors"] = h["recent_errors"][-3:]

        for tool, h in health.items():
            h["avg_ms"] = round(h["total_ms"] / max(h["calls"], 1))
            h["reliability"] = round((h["successes"] / max(h["calls"], 1)) * 100, 1)

        return dict(health)

    def get_unreliable_tools(self, threshold: float = 70.0) -> list[str]:
        health = self.get_tool_health()
        return [
            tool for tool, h in health.items()
            if h["reliability"] < threshold and h["calls"] >= 3
        ]

    def get_slow_tools(self, threshold_ms: int = 10000) -> list[dict]:
        health = self.get_tool_health()
        return [
            {"tool": tool, "avg_ms": h["avg_ms"], "calls": h["calls"]}
            for tool, h in health.items()
            if h["avg_ms"] > threshold_ms and h["calls"] >= 2
        ]


class ObservabilityBrain:
    def __init__(self):
        self.tracker = ToolTracker()

    def record_execution(self, tool_name: str, duration_ms: int, success: bool,
                         error: str = "", arguments: dict | None = None,
                         result: dict | None = None):
        self.tracker.record(
            tool_name, duration_ms, success, error,
            len(json.dumps(arguments or {})),
            len(json.dumps(result or {})),
        )

    async def get_system_intelligence(self) -> dict:
        health = self.tracker.get_tool_health()
        unreliable = self.tracker.get_unreliable_tools()
        slow = self.tracker.get_slow_tools()

        async with async_session() as db:
            now = datetime.now(timezone.utc)
            day_ago = now - timedelta(days=1)
            week_ago = now - timedelta(days=7)

            daily_msgs = (await db.execute(
                select(func.count(Message.id)).where(Message.created_at >= day_ago)
            )).scalar() or 0

            weekly_msgs = (await db.execute(
                select(func.count(Message.id)).where(Message.created_at >= week_ago)
            )).scalar() or 0

            daily_tools = (await db.execute(
                select(func.count(ToolExecution.id)).where(ToolExecution.created_at >= day_ago)
            )).scalar() or 0

            daily_failures = (await db.execute(
                select(func.count(ToolExecution.id)).where(
                    ToolExecution.created_at >= day_ago,
                    ToolExecution.status == "failed",
                )
            )).scalar() or 0

            daily_chars = (await db.execute(
                select(func.sum(func.length(Message.content))).where(
                    Message.created_at >= day_ago, Message.role.in_(["user", "assistant"])
                )
            )).scalar() or 0

        est_daily_tokens = int(daily_chars / 4)
        est_daily_cost = (est_daily_tokens * 2.50 / 1_000_000) + (est_daily_tokens * 10.00 / 1_000_000)

        recommendations = []
        if unreliable:
            recommendations.append({
                "type": "reliability",
                "message": f"Tools with low reliability: {', '.join(unreliable)}. Consider using alternatives or investigating root causes.",
                "priority": "high",
            })
        if slow:
            tool_names = [s["tool"] for s in slow]
            recommendations.append({
                "type": "performance",
                "message": f"Slow tools (>10s avg): {', '.join(tool_names)}. These may benefit from caching or optimisation.",
                "priority": "medium",
            })
        if est_daily_cost > 1.0:
            recommendations.append({
                "type": "cost",
                "message": f"Daily cost estimate: ${est_daily_cost:.2f}. Consider using GPT-4o-mini for simple tasks to reduce costs.",
                "priority": "medium",
            })
        if daily_failures > 5:
            recommendations.append({
                "type": "errors",
                "message": f"{daily_failures} tool failures in the last 24h. Check recent errors for patterns.",
                "priority": "high",
            })

        return {
            "activity": {
                "messages_24h": daily_msgs,
                "messages_7d": weekly_msgs,
                "tool_calls_24h": daily_tools,
                "failures_24h": daily_failures,
            },
            "cost": {
                "estimated_daily_tokens": est_daily_tokens,
                "estimated_daily_cost_usd": round(est_daily_cost, 4),
                "estimated_monthly_cost_usd": round(est_daily_cost * 30, 2),
            },
            "tool_health": {
                tool: {
                    "reliability": h["reliability"],
                    "avg_ms": h.get("avg_ms", 0),
                    "calls_24h": h["calls"],
                }
                for tool, h in health.items()
            },
            "unreliable_tools": unreliable,
            "slow_tools": slow,
            "recommendations": recommendations,
        }

    def get_tool_advisory(self, tool_name: str) -> str:
        health = self.tracker.get_tool_health()
        h = health.get(tool_name)
        if not h:
            return ""

        advisories = []
        if h["reliability"] < 50:
            advisories.append(f"WARNING: {tool_name} has very low reliability ({h['reliability']}%). Consider alternatives.")
        elif h["reliability"] < 80:
            advisories.append(f"CAUTION: {tool_name} reliability is {h['reliability']}%. Recent errors: {'; '.join(h['recent_errors'][:2])}")

        if h.get("avg_ms", 0) > 15000:
            advisories.append(f"SLOW: {tool_name} averages {h['avg_ms']}ms. Expect delays.")

        return " | ".join(advisories)


observability = ObservabilityBrain()

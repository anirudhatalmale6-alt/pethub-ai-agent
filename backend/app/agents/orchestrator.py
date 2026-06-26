from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


@dataclass
class Step:
    id: int
    description: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    result: Any = None
    error: str | None = None


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    status: str = "planning"
    summary: str = ""


PLANNER_PROMPT = """You are a task planning agent. Break down the user's request into a clear sequence of steps.

Available tools:
{tools}

For each step, specify:
- description: what this step accomplishes
- tool: which tool to use (or null for a reasoning/response step)
- arguments: the arguments to pass to the tool

Respond with a JSON object:
{{
  "goal": "summary of the user's goal",
  "steps": [
    {{"description": "...", "tool": "tool_name or null", "arguments": {{...}} }},
    ...
  ]
}}

Keep plans concise. Only include steps that are necessary. If the request can be handled in 1-2 steps, don't add unnecessary steps."""

REVIEWER_PROMPT = """You are a quality reviewer agent. Review the results of an executed plan and provide a summary.

The original goal was: {goal}

Steps executed:
{steps}

Provide a clear, concise summary of:
1. What was accomplished
2. Any issues or errors encountered
3. Recommendations for follow-up actions (if any)

Be direct and factual."""


class Orchestrator:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def plan(self, user_request: str, context: str = "") -> Plan:
        tools_desc = "\n".join(
            f"- {t.name}: {t.description} (approval_required={t.requires_approval})"
            for t in registry.list_tools()
        )

        prompt = PLANNER_PROMPT.format(tools=tools_desc)
        messages = [
            {"role": "system", "content": prompt},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": user_request})

        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return Plan(goal=user_request, steps=[
                Step(id=1, description="Execute request directly", tool=None)
            ])

        steps = []
        for i, s in enumerate(data.get("steps", []), 1):
            steps.append(Step(
                id=i,
                description=s.get("description", ""),
                tool=s.get("tool"),
                arguments=s.get("arguments", {}),
            ))

        return Plan(goal=data.get("goal", user_request), steps=steps)

    async def execute_plan(self, plan: Plan) -> AsyncGenerator[dict, None]:
        plan.status = "executing"

        for step in plan.steps:
            step.status = "running"
            yield {
                "type": "step_start",
                "step_id": step.id,
                "description": step.description,
                "tool": step.tool,
            }

            if step.tool:
                tool_def = registry.get(step.tool)
                if not tool_def:
                    step.status = "failed"
                    step.error = f"Unknown tool: {step.tool}"
                    yield {"type": "step_error", "step_id": step.id, "error": step.error}
                    continue

                if tool_def.requires_approval:
                    step.status = "awaiting_approval"
                    yield {
                        "type": "step_approval_required",
                        "step_id": step.id,
                        "tool": step.tool,
                        "arguments": step.arguments,
                        "description": step.description,
                    }
                    continue

                try:
                    result = await registry.execute(step.tool, step.arguments)
                    step.result = result
                    step.status = "completed"
                    yield {
                        "type": "step_result",
                        "step_id": step.id,
                        "tool": step.tool,
                        "result": result if isinstance(result, dict) else {"output": str(result)},
                    }
                except Exception as e:
                    step.status = "failed"
                    step.error = str(e)
                    yield {"type": "step_error", "step_id": step.id, "error": str(e)}
            else:
                step.status = "completed"
                yield {"type": "step_reasoning", "step_id": step.id, "description": step.description}

        plan.status = "reviewing"
        summary = await self.review(plan)
        plan.summary = summary
        plan.status = "completed"

        yield {"type": "plan_complete", "summary": summary}

    async def review(self, plan: Plan) -> str:
        steps_desc = "\n".join(
            f"Step {s.id}: {s.description}\n  Status: {s.status}\n  Tool: {s.tool or 'none'}\n  "
            f"Result: {json.dumps(s.result)[:300] if s.result else 'N/A'}\n  "
            f"Error: {s.error or 'none'}"
            for s in plan.steps
        )

        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": REVIEWER_PROMPT.format(goal=plan.goal, steps=steps_desc)},
                {"role": "user", "content": "Please review the execution results."},
            ],
            temperature=0.3,
        )

        return response.choices[0].message.content or "Plan execution completed."

    async def approve_step(self, plan: Plan, step_id: int) -> dict:
        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step:
            return {"error": f"Step {step_id} not found"}
        if step.status != "awaiting_approval":
            return {"error": f"Step {step_id} is not awaiting approval"}

        try:
            result = await registry.execute(step.tool, step.arguments)
            step.result = result
            step.status = "completed"
            return {"status": "completed", "result": result if isinstance(result, dict) else {"output": str(result)}}
        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            return {"status": "failed", "error": str(e)}

    async def reject_step(self, plan: Plan, step_id: int) -> dict:
        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step:
            return {"error": f"Step {step_id} not found"}
        step.status = "rejected"
        return {"status": "rejected"}

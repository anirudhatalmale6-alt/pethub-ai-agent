import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.database import async_session
from app.tools.registry import registry

logger = logging.getLogger(__name__)

DIAGNOSE_PROMPT = """You are a debug agent. A tool execution failed. Diagnose the root cause and suggest a fix.

Tool: {tool_name}
Arguments: {arguments}
Error: {error}

Available tools: {available_tools}

Return JSON:
{{
    "diagnosis": "What went wrong and why",
    "root_cause": "specific|auth|not_found|timeout|rate_limit|bad_params|server_error|unknown",
    "can_self_heal": true/false,
    "fix_strategy": "retry|modify_params|switch_tool|switch_endpoint|none",
    "fixed_tool": "tool name to use instead (or same tool)",
    "fixed_arguments": {{...modified arguments that should work...}},
    "explanation": "Human-readable explanation of what happened and what we're trying"
}}

Common fixes:
- 404 on /wp/v2/posts/ID: try /wp/v2/pages/ID instead (ID might be a page not a post)
- 401 Unauthorized: credentials issue, cannot self-heal
- 400 Bad Request: parameter format issue, adjust parameters
- Timeout: retry with same parameters
- Rate limit: wait and retry
- "no results": try different search query or broader terms

If you cannot fix it, set can_self_heal to false and provide a clear diagnosis."""


class SelfHealEngine:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.max_heal_attempts = 2

    async def diagnose_and_heal(self, tool_name: str, arguments: dict,
                                 error: str, attempt: int = 0) -> dict[str, Any]:
        if attempt >= self.max_heal_attempts:
            return {
                "healed": False,
                "diagnosis": f"Failed after {attempt} self-heal attempts",
                "original_error": error,
            }

        available = [f"{t.name}: {t.description[:60]}" for t in registry.list_tools()]

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": DIAGNOSE_PROMPT.format(
                        tool_name=tool_name,
                        arguments=json.dumps(arguments)[:1000],
                        error=error[:500],
                        available_tools="\n".join(available),
                    )},
                    {"role": "user", "content": "Diagnose and fix."},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            diagnosis = json.loads(response.choices[0].message.content or "{}")
        except Exception as e:
            logger.exception("Self-heal diagnosis failed")
            return {"healed": False, "diagnosis": f"Diagnosis failed: {e}", "original_error": error}

        if not diagnosis.get("can_self_heal", False):
            return {
                "healed": False,
                "diagnosis": diagnosis.get("diagnosis", "Unknown error"),
                "root_cause": diagnosis.get("root_cause", "unknown"),
                "explanation": diagnosis.get("explanation", error),
                "original_error": error,
            }

        fixed_tool = diagnosis.get("fixed_tool", tool_name)
        fixed_args = diagnosis.get("fixed_arguments", arguments)

        if not registry.get(fixed_tool):
            return {
                "healed": False,
                "diagnosis": f"Suggested tool '{fixed_tool}' doesn't exist",
                "original_error": error,
            }

        logger.info(f"Self-heal attempt {attempt + 1}: {tool_name} -> {fixed_tool} with {json.dumps(fixed_args)[:200]}")

        try:
            result = await registry.execute(fixed_tool, fixed_args)
            result_dict = result if isinstance(result, dict) else {"output": str(result)}

            if result_dict.get("error"):
                return await self.diagnose_and_heal(fixed_tool, fixed_args, str(result_dict["error"]), attempt + 1)

            return {
                "healed": True,
                "original_tool": tool_name,
                "fixed_tool": fixed_tool,
                "fix_strategy": diagnosis.get("fix_strategy", ""),
                "explanation": diagnosis.get("explanation", ""),
                "result": result_dict,
                "attempts": attempt + 1,
            }

        except Exception as e:
            return await self.diagnose_and_heal(fixed_tool, fixed_args, str(e), attempt + 1)

    def classify_error(self, error: str) -> str:
        error_lower = error.lower()

        if "401" in error or "unauthorized" in error_lower:
            return "auth"
        if "404" in error or "not found" in error_lower:
            return "not_found"
        if "429" in error or "rate limit" in error_lower:
            return "rate_limit"
        if "timeout" in error_lower or "timed out" in error_lower:
            return "timeout"
        if "400" in error or "bad request" in error_lower:
            return "bad_params"
        if "500" in error or "502" in error or "503" in error:
            return "server_error"
        if "connection" in error_lower:
            return "connection"

        return "unknown"

    def can_quick_fix(self, tool_name: str, error: str, arguments: dict) -> dict | None:
        error_type = self.classify_error(error)

        if error_type == "not_found" and tool_name in ("wp_update_post", "wp_get_post", "wp_delete_post"):
            current_type = arguments.get("post_type", "posts")
            new_type = "pages" if current_type == "posts" else "posts"
            return {
                "tool": tool_name,
                "arguments": {**arguments, "post_type": new_type},
                "reason": f"ID not found in {current_type}, trying {new_type}",
            }

        if error_type == "timeout":
            return {
                "tool": tool_name,
                "arguments": arguments,
                "reason": "Timeout - retrying",
            }

        if error_type == "rate_limit":
            return {
                "tool": tool_name,
                "arguments": arguments,
                "reason": "Rate limited - retrying after delay",
                "delay": 3,
            }

        return None


self_heal_engine = SelfHealEngine()

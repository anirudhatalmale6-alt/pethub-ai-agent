from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Any

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.models import Message, ToolExecution, AuditLog, Conversation
from app.tools.registry import registry

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    type: str  # text_delta, tool_start, tool_result, tool_approval_required, error, done
    data: dict[str, Any]


SYSTEM_PROMPT_BASE = """You are PetHub AI Agent, an intelligent operations assistant. You help manage websites, generate content, analyse data, and execute tasks using the tools available to you.

Key behaviours:
- Always explain what you plan to do before executing tools
- For sensitive operations (bulk edits, plugin installs, site-wide changes), describe the action and wait for approval
- Provide clear summaries of what was done after tool execution
- If a tool fails, explain the error and suggest alternatives
- Be concise but thorough in your responses

You have access to various tools for WordPress management, code generation, SEO analysis, and more. Use them when the user's request requires action, not just information.

IMPORTANT - WordPress credentials are pre-configured on the server. When using any WordPress tool (wp_list_posts, wp_create_post, wp_update_post, etc.), do NOT ask the user for wp_url, wp_user, or wp_password. Just leave those parameters empty or omit them — the system will automatically use the stored credentials. Simply execute the tool directly when the user asks for WordPress operations.

MEMORY - You have remember/recall/forget tools for explicit storage. You also have a contextual memory system that automatically learns from conversations.

SELF-IMPROVEMENT - After completing tasks, the system evaluates outcomes and learns improvement rules. You can use 'evaluate_content' to score any post, 'get_improvement_tips' to see what you've learned, and 'performance_report' for trends. Apply learned rules automatically when creating content or executing tasks."""


async def _build_system_prompt(user_message: str = "") -> str:
    from app.agents.memory import memory_engine
    from app.agents.feedback import feedback_engine

    prompt = SYSTEM_PROMPT_BASE

    try:
        context = await memory_engine.get_relevant_context(user_message)
        if context:
            prompt += "\n\n" + context
    except Exception:
        pass

    try:
        content_rules = await feedback_engine.get_improvement_rules("content_creation")
        general_rules = await feedback_engine.get_improvement_rules("")
        all_rules = list(dict.fromkeys(content_rules + general_rules))[:15]
        if all_rules:
            prompt += "\n\nLEARNED IMPROVEMENT RULES (apply these automatically):\n"
            for rule in all_rules:
                prompt += f"- {rule}\n"
    except Exception:
        pass

    try:
        from app.agents.observability import observability
        unreliable = observability.tracker.get_unreliable_tools()
        if unreliable:
            prompt += f"\n\nTOOL ADVISORIES: These tools have low reliability and may fail: {', '.join(unreliable)}. Prefer alternatives when possible."
    except Exception:
        pass

    try:
        from app.agents.autonomy import autonomy
        prompt += f"\n\nAUTONOMY LEVEL: {autonomy.level} ({autonomy.level_name}) - {autonomy.level_description}"
        if autonomy.level == 1:
            prompt += "\nIMPORTANT: You are in SUGGEST ONLY mode. Explain what you would do but do NOT call any tools. Only provide recommendations."
    except Exception:
        pass

    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        if ws:
            prompt += "\n" + ws.get_context_prompt()
            prompt += "\nIMPORTANT: All actions are scoped to this workspace ONLY. Do not reference or modify any other workspace's content."
        else:
            workspaces = workspace_manager.list_all()
            if workspaces:
                prompt += f"\n\nWORKSPACES AVAILABLE: {', '.join(w['name'] for w in workspaces)}. Ask the user which workspace to work in, or suggest they switch with 'switch to [name]'."
    except Exception:
        pass

    return prompt


class AgentEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.max_iterations = self.settings.max_tool_iterations

    async def _build_messages(self, conversation: Conversation, user_message: str = "") -> list[dict]:
        from sqlalchemy import select as sa_select
        from app.models.models import Message as MsgModel

        result = await self.db.execute(
            sa_select(MsgModel)
            .where(MsgModel.conversation_id == conversation.id)
            .order_by(MsgModel.created_at)
        )
        db_messages = result.scalars().all()

        system_prompt = await _build_system_prompt(user_message)
        messages = [{"role": "system", "content": system_prompt}]

        valid_tool_call_ids: set[str] = set()

        for msg in db_messages:
            if msg.role == "tool":
                if not msg.tool_call_id or msg.tool_call_id not in valid_tool_call_ids:
                    continue
                messages.append({
                    "role": "tool",
                    "content": msg.content or '{"status": "no result"}',
                    "tool_call_id": msg.tool_call_id,
                })
                continue

            entry: dict[str, Any] = {"role": msg.role}
            if msg.role == "assistant" and msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and tc.get("id"):
                        valid_tool_call_ids.add(tc["id"])
                if msg.content:
                    entry["content"] = msg.content
            else:
                entry["content"] = msg.content or ""

            messages.append(entry)

        return messages

    def _check_approval_required(self, tool_name: str, arguments: dict) -> bool:
        from app.agents.autonomy import autonomy
        return autonomy.requires_approval(tool_name)

    async def _save_message(self, conversation_id: str, role: str, content: str | None = None,
                            tool_calls: list | None = None, tool_call_id: str | None = None) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def _log_audit(self, user_id: str | None, action: str, resource_type: str | None = None,
                         resource_id: str | None = None, details: dict | None = None) -> None:
        log = AuditLog(user_id=user_id, action=action, resource_type=resource_type,
                       resource_id=resource_id, details=details)
        self.db.add(log)

    async def _execute_tool(self, conversation_id: str, message_id: str,
                            tool_name: str, arguments: dict) -> ToolExecution:
        needs_approval = self._check_approval_required(tool_name, arguments)

        execution = ToolExecution(
            conversation_id=conversation_id,
            message_id=message_id,
            tool_name=tool_name,
            arguments=arguments,
            requires_approval=needs_approval,
            status="awaiting_approval" if needs_approval else "executing",
        )
        self.db.add(execution)
        await self.db.flush()

        if needs_approval:
            return execution

        start = time.monotonic()
        try:
            result = await registry.execute(tool_name, arguments)
            execution.result = result if isinstance(result, dict) else {"output": str(result)}
            execution.status = "completed"
            execution.duration_ms = int((time.monotonic() - start) * 1000)

            try:
                from app.agents.observability import observability
                observability.record_execution(tool_name, execution.duration_ms, True, arguments=arguments, result=execution.result)
            except Exception:
                pass

            try:
                from app.agents.feedback import feedback_engine
                evaluatable = ["wp_create_post", "wp_update_post", "wp_update_seo_meta",
                               "generate_wp_plugin", "generate_code"]
                if tool_name in evaluatable:
                    asyncio.create_task(feedback_engine.evaluate_action(
                        tool_name, str(arguments)[:255], execution.result, conversation_id
                    ))
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"Tool execution failed: {tool_name} - {e}. Attempting self-heal...")
            execution.duration_ms = int((time.monotonic() - start) * 1000)

            try:
                from app.agents.self_heal import self_heal_engine

                quick = self_heal_engine.can_quick_fix(tool_name, str(e), arguments)
                if quick:
                    if quick.get("delay"):
                        await asyncio.sleep(quick["delay"])
                    try:
                        retry_result = await registry.execute(quick["tool"], quick["arguments"])
                        execution.result = retry_result if isinstance(retry_result, dict) else {"output": str(retry_result)}
                        execution.result["_self_healed"] = True
                        execution.result["_heal_reason"] = quick["reason"]
                        execution.status = "completed"
                        logger.info(f"Quick self-heal succeeded: {quick['reason']}")
                        await self.db.flush()
                        return execution
                    except Exception:
                        pass

                heal_result = await self_heal_engine.diagnose_and_heal(tool_name, arguments, str(e))

                if heal_result.get("healed"):
                    execution.result = heal_result["result"]
                    execution.result["_self_healed"] = True
                    execution.result["_heal_explanation"] = heal_result.get("explanation", "")
                    execution.status = "completed"
                    logger.info(f"Self-heal succeeded: {heal_result.get('explanation', '')}")
                else:
                    execution.error = heal_result.get("explanation", str(e))
                    execution.status = "failed"
                    logger.info(f"Self-heal failed: {heal_result.get('diagnosis', '')}")
            except Exception as heal_err:
                logger.exception("Self-heal system error")
                execution.error = str(e)
                execution.status = "failed"

            try:
                from app.agents.feedback import feedback_engine
                asyncio.create_task(feedback_engine.evaluate_action(
                    tool_name, str(arguments)[:255],
                    {"error": execution.error or str(e), "status": execution.status}, conversation_id
                ))
            except Exception:
                pass

        await self.db.flush()
        return execution

    async def run(self, conversation: Conversation, user_message: str,
                  user_id: str) -> AsyncGenerator[StreamEvent, None]:
        await self._save_message(conversation.id, "user", content=user_message)
        await self._log_audit(user_id, "user_message", "conversation", conversation.id)

        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            messages = await self._build_messages(conversation, user_message)
            tools = registry.get_openai_tools()

            kwargs: dict[str, Any] = {
                "model": self.settings.openai_model,
                "messages": messages,
                "stream": True,
            }
            if tools:
                kwargs["tools"] = tools

            collected_content = ""
            collected_tool_calls: list[dict] = []
            current_tool_calls: dict[int, dict] = {}

            try:
                stream = await self.client.chat.completions.create(**kwargs)

                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    if delta.content:
                        collected_content += delta.content
                        yield StreamEvent(type="text_delta", data={"content": delta.content})

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in current_tool_calls:
                                current_tool_calls[idx] = {
                                    "id": tc.id or "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if tc.id:
                                current_tool_calls[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    current_tool_calls[idx]["function"]["name"] = tc.function.name
                                if tc.function.arguments:
                                    current_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

                    if chunk.choices[0].finish_reason == "stop":
                        break
                    if chunk.choices[0].finish_reason == "tool_calls":
                        break

            except Exception as e:
                from openai import RateLimitError, APIConnectionError, APITimeoutError
                if isinstance(e, (RateLimitError, APIConnectionError, APITimeoutError)) and iteration < 3:
                    logger.warning(f"OpenAI transient error (attempt {iteration}): {e}")
                    yield StreamEvent(type="text_delta", data={"content": "One moment, retrying..."})
                    await asyncio.sleep(2 ** iteration)
                    continue
                logger.exception("OpenAI API error")
                yield StreamEvent(type="error", data={"message": str(e)})
                return

            if current_tool_calls:
                collected_tool_calls = [current_tool_calls[i] for i in sorted(current_tool_calls.keys())]

            assistant_msg = await self._save_message(
                conversation.id, "assistant",
                content=collected_content or None,
                tool_calls=collected_tool_calls or None,
            )

            if not collected_tool_calls:
                break

            for tc in collected_tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                yield StreamEvent(type="tool_start", data={
                    "tool_call_id": tc["id"],
                    "tool_name": tool_name,
                    "arguments": arguments,
                })

                execution = await self._execute_tool(
                    conversation.id, assistant_msg.id, tool_name, arguments
                )

                await self._log_audit(
                    user_id, "tool_execution", "tool", tool_name,
                    {"arguments": arguments, "status": execution.status, "execution_id": execution.id},
                )

                if execution.status == "awaiting_approval":
                    yield StreamEvent(type="tool_approval_required", data={
                        "execution_id": execution.id,
                        "tool_call_id": tc["id"],
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "description": f"The action '{tool_name}' requires your approval before execution.",
                    })
                    tool_result_content = json.dumps({
                        "status": "awaiting_approval",
                        "message": "This action requires user approval. Waiting for confirmation.",
                    })
                else:
                    result_data = execution.result if execution.status == "completed" else {"error": execution.error}
                    yield StreamEvent(type="tool_result", data={
                        "tool_call_id": tc["id"],
                        "tool_name": tool_name,
                        "status": execution.status,
                        "result": result_data,
                    })
                    tool_result_content = json.dumps(result_data)

                await self._save_message(
                    conversation.id, "tool",
                    content=tool_result_content,
                    tool_call_id=tc["id"],
                )

            has_pending = any(
                tc["function"]["name"] and self._check_approval_required(
                    tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}")
                )
                for tc in collected_tool_calls
            )
            if has_pending:
                break

        await self.db.commit()

        try:
            import asyncio
            from app.agents.memory import memory_engine
            asyncio.create_task(memory_engine.extract_and_store(conversation.id))
        except Exception:
            pass

        yield StreamEvent(type="done", data={})

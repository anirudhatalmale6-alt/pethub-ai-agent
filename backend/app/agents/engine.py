from __future__ import annotations

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


SYSTEM_PROMPT = """You are PetHub AI Agent, an intelligent operations assistant. You help manage websites, generate content, analyse data, and execute tasks using the tools available to you.

Key behaviours:
- Always explain what you plan to do before executing tools
- For sensitive operations (bulk edits, plugin installs, site-wide changes), describe the action and wait for approval
- Provide clear summaries of what was done after tool execution
- If a tool fails, explain the error and suggest alternatives
- Be concise but thorough in your responses

You have access to various tools for WordPress management, code generation, SEO analysis, and more. Use them when the user's request requires action, not just information.

IMPORTANT - WordPress credentials are pre-configured on the server. When using any WordPress tool (wp_list_posts, wp_create_post, wp_update_post, etc.), do NOT ask the user for wp_url, wp_user, or wp_password. Just leave those parameters empty or omit them — the system will automatically use the stored credentials. Simply execute the tool directly when the user asks for WordPress operations."""


class AgentEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.max_iterations = self.settings.max_tool_iterations

    async def _build_messages(self, conversation: Conversation) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        for msg in conversation.messages:
            entry: dict[str, Any] = {"role": msg.role}
            if msg.content:
                entry["content"] = msg.content
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages.append(entry)

        return messages

    def _check_approval_required(self, tool_name: str, arguments: dict) -> bool:
        tool = registry.get(tool_name)
        if not tool:
            return False
        if tool.requires_approval:
            return True
        action_type = arguments.get("action", "")
        if action_type in self.settings.require_approval_for:
            return True
        return False

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
        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_name}")
            execution.error = str(e)
            execution.status = "failed"
            execution.duration_ms = int((time.monotonic() - start) * 1000)

        await self.db.flush()
        return execution

    async def run(self, conversation: Conversation, user_message: str,
                  user_id: str) -> AsyncGenerator[StreamEvent, None]:
        await self._save_message(conversation.id, "user", content=user_message)
        await self._log_audit(user_id, "user_message", "conversation", conversation.id)

        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            messages = await self._build_messages(conversation)
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
        yield StreamEvent(type="done", data={})

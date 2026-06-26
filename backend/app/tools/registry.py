from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]
    category: str = "general"
    requires_approval: bool = False
    tags: list[str] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Awaitable[Any]],
        category: str = "general",
        requires_approval: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            category=category,
            requires_approval=requires_approval,
            tags=tags or [],
        )
        logger.info(f"Registered tool: {name} (category={category}, approval={requires_approval})")

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        category: str = "general",
        requires_approval: bool = False,
        tags: list[str] | None = None,
    ):
        def decorator(func: Callable[..., Awaitable[Any]]):
            self.register(name, description, parameters, func, category, requires_approval, tags)
            return func
        return decorator

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def get_openai_tools(self, category: str | None = None) -> list[dict]:
        return [t.to_openai_schema() for t in self.list_tools(category)]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        sig = inspect.signature(tool.handler)
        filtered_args = {k: v for k, v in arguments.items() if k in sig.parameters}
        return await tool.handler(**filtered_args)


registry = ToolRegistry()

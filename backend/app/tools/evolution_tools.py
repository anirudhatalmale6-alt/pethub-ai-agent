import logging

from app.tools.registry import registry
from app.agents.evolution import evolution_engine

logger = logging.getLogger(__name__)


@registry.tool(
    name="propose_module",
    description="Propose a new tool or workflow for the system. The system designs and generates the code, saves it to sandbox for testing. Use when you identify a capability gap or the user requests a new integration.",
    parameters={
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "Description of the new tool/capability needed"},
        },
        "required": ["request"],
    },
    category="evolution",
)
async def propose_module(request: str = "") -> dict:
    return await evolution_engine.propose(request)


@registry.tool(
    name="sandbox_test",
    description="Run sandbox testing on a proposed module. Checks security, validates syntax, generates test scenarios, and scores quality. Module must pass sandbox before activation.",
    parameters={
        "type": "object",
        "properties": {
            "module_id": {"type": "string", "description": "Module ID from propose_module"},
        },
        "required": ["module_id"],
    },
    category="evolution",
)
async def sandbox_test(module_id: str = "") -> dict:
    return await evolution_engine.sandbox_test(module_id)


@registry.tool(
    name="activate_module",
    description="Activate a sandbox-tested module into production. Only works if the module passed sandbox testing. New tools become immediately available.",
    parameters={
        "type": "object",
        "properties": {
            "module_id": {"type": "string", "description": "Module ID that passed sandbox testing"},
        },
        "required": ["module_id"],
    },
    category="evolution",
    requires_approval=True,
)
async def activate_module(module_id: str = "") -> dict:
    return await evolution_engine.activate(module_id)


@registry.tool(
    name="rollback_module",
    description="Roll back an activated module. Removes its tools and archives the code. Use if an activated module causes issues.",
    parameters={
        "type": "object",
        "properties": {
            "module_id": {"type": "string", "description": "Module ID to roll back"},
        },
        "required": ["module_id"],
    },
    category="evolution",
    requires_approval=True,
)
async def rollback_module(module_id: str = "") -> dict:
    return await evolution_engine.rollback(module_id)


@registry.tool(
    name="list_modules",
    description="List all proposed, tested, active, and rolled-back modules in the evolution registry.",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status", "default": "", "enum": ["", "proposed", "sandbox_passed", "sandbox_failed", "active", "rolled_back"]},
        },
    },
    category="evolution",
)
async def list_modules(status: str = "") -> dict:
    modules = evolution_engine.registry.list_all(status)
    return {
        "count": len(modules),
        "modules": [
            {
                "id": m["id"],
                "request": m.get("request", "")[:80],
                "status": m.get("status", ""),
                "version": m.get("version", 1),
                "quality_score": m.get("quality_score", "N/A"),
                "new_tools": m.get("new_tools", []),
                "created_at": m.get("created_at", ""),
            }
            for m in modules
        ],
    }

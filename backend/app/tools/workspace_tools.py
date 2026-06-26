import logging

from app.tools.registry import registry
from app.agents.workspace import workspace_manager

logger = logging.getLogger(__name__)


@registry.tool(
    name="create_workspace",
    description="Create a new workspace for a website/project. Each workspace has its own WordPress credentials, memory, SEO rules, and content rules. Keeps projects completely isolated.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workspace name (e.g. 'Pet Hub', 'Comparison Site')"},
            "domain": {"type": "string", "description": "Website domain (e.g. 'pethubonline.com')"},
            "wp_url": {"type": "string", "description": "WordPress URL (defaults to https://domain)", "default": ""},
            "wp_user": {"type": "string", "description": "WordPress application password username", "default": ""},
            "wp_password": {"type": "string", "description": "WordPress application password", "default": ""},
            "description": {"type": "string", "description": "Brief description of this project", "default": ""},
            "affiliate_tag": {"type": "string", "description": "Amazon affiliate tag for this site", "default": ""},
        },
        "required": ["name", "domain"],
    },
    category="workspace",
)
async def create_workspace(name: str = "", domain: str = "", wp_url: str = "",
                            wp_user: str = "", wp_password: str = "",
                            description: str = "", affiliate_tag: str = "") -> dict:
    try:
        ws = workspace_manager.create(name, domain, wp_url, wp_user, wp_password, description, affiliate_tag)
        return {
            "status": "created",
            "workspace_id": ws.id,
            "name": ws.name,
            "domain": ws.domain,
            "active": ws.id == workspace_manager._active_id,
            "message": f"Workspace '{name}' created for {domain}.",
        }
    except ValueError as e:
        return {"error": str(e)}


@registry.tool(
    name="switch_workspace",
    description="Switch to a different workspace. All subsequent tool calls will use this workspace's credentials, memory, and rules.",
    parameters={
        "type": "object",
        "properties": {
            "workspace": {"type": "string", "description": "Workspace name, slug, or ID to switch to"},
        },
        "required": ["workspace"],
    },
    category="workspace",
)
async def switch_workspace(workspace: str = "") -> dict:
    ws = workspace_manager.switch(workspace)
    if not ws:
        available = workspace_manager.list_all()
        return {
            "error": f"Workspace '{workspace}' not found",
            "available": [w["name"] for w in available],
        }
    return {
        "status": "switched",
        "workspace_id": ws.id,
        "name": ws.name,
        "domain": ws.domain,
        "message": f"Now working in workspace: {ws.name} ({ws.domain}). All tools scoped to this workspace.",
    }


@registry.tool(
    name="list_workspaces",
    description="List all workspaces and show which one is currently active.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="workspace",
)
async def list_workspaces() -> dict:
    workspaces = workspace_manager.list_all()
    active = workspace_manager.active
    return {
        "count": len(workspaces),
        "active_workspace": active.name if active else "None",
        "workspaces": workspaces,
    }


@registry.tool(
    name="set_workspace_rules",
    description="Set SEO rules or content rules for the active workspace. These rules are applied automatically when working in this workspace.",
    parameters={
        "type": "object",
        "properties": {
            "seo_rules": {
                "type": "array",
                "items": {"type": "string"},
                "description": "SEO rules for this workspace (e.g. 'Always target UK keywords', 'Meta descriptions 120-155 chars')",
            },
            "content_rules": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Content creation rules (e.g. 'Use British English', 'Include FAQ section', 'Always add comparison table')",
            },
        },
    },
    category="workspace",
)
async def set_workspace_rules(seo_rules: list[str] | None = None,
                               content_rules: list[str] | None = None) -> dict:
    active = workspace_manager.active
    if not active:
        return {"error": "No active workspace. Create or switch to a workspace first."}

    ws = workspace_manager.update_rules(active.id, seo_rules, content_rules)
    if not ws:
        return {"error": "Failed to update rules"}

    return {
        "workspace": ws.name,
        "seo_rules": ws.seo_rules,
        "content_rules": ws.content_rules,
        "message": "Rules updated for this workspace.",
    }


@registry.tool(
    name="remove_workspace",
    description="Remove a workspace permanently.",
    parameters={
        "type": "object",
        "properties": {
            "workspace": {"type": "string", "description": "Workspace name, slug, or ID to remove"},
        },
        "required": ["workspace"],
    },
    category="workspace",
    requires_approval=True,
)
async def remove_workspace(workspace: str = "") -> dict:
    removed = workspace_manager.remove(workspace)
    return {"removed": removed, "workspace": workspace}

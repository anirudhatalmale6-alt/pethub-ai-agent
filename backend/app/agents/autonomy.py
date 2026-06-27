import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

AUTONOMY_FILE = os.environ.get("AUTONOMY_FILE", "/app/config/autonomy.json")

LEVELS = {
    1: {
        "name": "Suggest Only",
        "description": "Agent analyses and recommends but never executes tools. Pure advisory mode.",
        "auto_execute": set(),
        "needs_approval": "all",
    },
    2: {
        "name": "Approval Required",
        "description": "Read-only tools run freely. All write/modify actions need explicit approval.",
        "auto_execute": "read_only",
        "needs_approval": "all_writes",
    },
    3: {
        "name": "Smart Auto",
        "description": "Low-risk operations run automatically. High-risk actions still need approval.",
        "auto_execute": "low_risk",
        "needs_approval": "high_risk_only",
    },
    4: {
        "name": "Full Auto",
        "description": "Everything runs automatically except destructive operations (delete, bulk edit).",
        "auto_execute": "most",
        "needs_approval": "destructive_only",
    },
}

READ_ONLY_TOOLS = {
    "wp_list_posts", "wp_list_pages", "wp_get_post", "wp_list_categories",
    "wp_get_seo_meta", "seo_audit_page", "check_page_speed", "check_broken_links",
    "screenshot_and_analyse", "screenshot_compare", "analyse_uploaded_image",
    "ml_list_subscribers", "ml_list_campaigns", "ml_subscriber_stats", "ml_list_groups",
    "amazon_search", "amazon_product_details", "amazon_build_comparison",
    "recall", "get_improvement_tips", "performance_report", "evaluate_content",
    "check_job_status", "list_connectors", "list_projects", "list_goals",
    "get_goal_digest", "system_intelligence", "tool_health_check",
    "design_project", "crawl_site", "site_health_audit", "get_site_urls",
    "visual_site_check", "list_workspaces", "get_autonomy_status",
}

LOW_RISK_WRITE_TOOLS = {
    "wp_create_post",  # creates as draft
    "wp_update_post",
    "wp_update_seo_meta",
    "wp_upload_media",
    "remember",
    "forget",
    "generate_code",
    "generate_wp_plugin",
    "generate_api_connector",
    "set_goal",
    "toggle_goal",
    "ml_add_subscriber",
    "ml_create_campaign",  # creates as draft
}

HIGH_RISK_TOOLS = {
    "wp_delete_post",
    "deploy_plugin_wp_api",
    "deploy_plugin_sftp",
    "install_connector",
    "remove_goal",
    "run_background_task",
    "build_project",
}


class AutonomyController:
    def __init__(self):
        self._level = 2
        self._load()

    def _load(self):
        if os.path.exists(AUTONOMY_FILE):
            try:
                with open(AUTONOMY_FILE) as f:
                    data = json.load(f)
                    self._level = data.get("level", 2)
            except Exception:
                self._level = 2

    def _save(self):
        with open(AUTONOMY_FILE, "w") as f:
            json.dump({"level": self._level}, f)

    @property
    def level(self) -> int:
        return self._level

    @property
    def level_name(self) -> str:
        return LEVELS.get(self._level, LEVELS[2])["name"]

    @property
    def level_description(self) -> str:
        return LEVELS.get(self._level, LEVELS[2])["description"]

    def set_level(self, level: int) -> dict:
        if level not in LEVELS:
            return {"error": f"Invalid level. Choose 1-4."}
        self._level = level
        self._save()
        return {
            "level": level,
            "name": LEVELS[level]["name"],
            "description": LEVELS[level]["description"],
        }

    def requires_approval(self, tool_name: str) -> bool:
        if self._level == 1:
            return True

        if tool_name in READ_ONLY_TOOLS:
            return False

        if self._level == 2:
            return tool_name not in READ_ONLY_TOOLS

        if self._level == 3:
            if tool_name in LOW_RISK_WRITE_TOOLS:
                return False
            return True

        if self._level == 4:
            if tool_name in HIGH_RISK_TOOLS:
                return True
            return False

        return True

    def get_status(self) -> dict:
        level_info = LEVELS[self._level]

        auto_tools = []
        approval_tools = []
        from app.tools.registry import registry
        for tool in registry.list_tools():
            if self.requires_approval(tool.name):
                approval_tools.append(tool.name)
            else:
                auto_tools.append(tool.name)

        return {
            "level": self._level,
            "name": level_info["name"],
            "description": level_info["description"],
            "auto_execute_count": len(auto_tools),
            "approval_required_count": len(approval_tools),
            "available_levels": {
                k: {"name": v["name"], "description": v["description"]}
                for k, v in LEVELS.items()
            },
        }


autonomy = AutonomyController()

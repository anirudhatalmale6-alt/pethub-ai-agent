import json
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

WORKSPACES_FILE = os.environ.get("WORKSPACES_FILE", "/app/config/workspaces.json")


class Workspace:
    def __init__(self, data: dict):
        self.id: str = data.get("id", str(uuid.uuid4())[:8])
        self.name: str = data.get("name", "")
        self.slug: str = data.get("slug", "")
        self.domain: str = data.get("domain", "")
        self.wp_url: str = data.get("wp_url", "")
        self.wp_user: str = data.get("wp_user", "")
        self.wp_password: str = data.get("wp_password", "")
        self.description: str = data.get("description", "")
        self.seo_rules: list[str] = data.get("seo_rules", [])
        self.content_rules: list[str] = data.get("content_rules", [])
        self.affiliate_tag: str = data.get("affiliate_tag", "")
        self.created_at: str = data.get("created_at", "")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "slug": self.slug,
            "domain": self.domain, "wp_url": self.wp_url,
            "wp_user": self.wp_user, "wp_password": self.wp_password,
            "description": self.description, "seo_rules": self.seo_rules,
            "content_rules": self.content_rules, "affiliate_tag": self.affiliate_tag,
            "created_at": self.created_at,
        }

    def get_context_prompt(self) -> str:
        parts = [f"\nACTIVE WORKSPACE: {self.name} ({self.domain})"]
        if self.affiliate_tag:
            parts.append(f"Affiliate tag: {self.affiliate_tag}")
        if self.seo_rules:
            parts.append("SEO Rules:\n" + "\n".join(f"- {r}" for r in self.seo_rules))
        if self.content_rules:
            parts.append("Content Rules:\n" + "\n".join(f"- {r}" for r in self.content_rules))
        parts.append(f"WordPress: {self.wp_url} (credentials pre-loaded)")
        return "\n".join(parts)


class WorkspaceManager:
    def __init__(self):
        self._workspaces: dict[str, Workspace] = {}
        self._active_id: str | None = None
        self._load()

    def _load(self):
        if os.path.exists(WORKSPACES_FILE):
            try:
                with open(WORKSPACES_FILE) as f:
                    data = json.load(f)
                    for ws_data in data.get("workspaces", []):
                        ws = Workspace(ws_data)
                        self._workspaces[ws.id] = ws
                    self._active_id = data.get("active_id")
            except Exception:
                pass

    def _save(self):
        data = {
            "workspaces": [ws.to_dict() for ws in self._workspaces.values()],
            "active_id": self._active_id,
        }
        with open(WORKSPACES_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @property
    def active(self) -> Workspace | None:
        if self._active_id and self._active_id in self._workspaces:
            return self._workspaces[self._active_id]
        return None

    def create(self, name: str, domain: str, wp_url: str = "", wp_user: str = "",
               wp_password: str = "", description: str = "", affiliate_tag: str = "") -> Workspace:
        from datetime import datetime, timezone
        slug = name.lower().replace(" ", "_").replace("-", "_")

        for ws in self._workspaces.values():
            if ws.slug == slug:
                raise ValueError(f"Workspace '{name}' already exists")

        ws = Workspace({
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "slug": slug,
            "domain": domain,
            "wp_url": wp_url or f"https://{domain}",
            "wp_user": wp_user,
            "wp_password": wp_password,
            "description": description,
            "affiliate_tag": affiliate_tag,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._workspaces[ws.id] = ws

        if not self._active_id:
            self._active_id = ws.id

        self._save()
        return ws

    def switch(self, identifier: str) -> Workspace | None:
        for ws in self._workspaces.values():
            if ws.id == identifier or ws.slug == identifier or ws.name.lower() == identifier.lower():
                self._active_id = ws.id
                self._save()
                return ws
        return None

    def remove(self, identifier: str) -> bool:
        ws = None
        for w in self._workspaces.values():
            if w.id == identifier or w.slug == identifier:
                ws = w
                break
        if not ws:
            return False

        del self._workspaces[ws.id]
        if self._active_id == ws.id:
            self._active_id = next(iter(self._workspaces), None) if self._workspaces else None
        self._save()
        return True

    def list_all(self) -> list[dict]:
        return [
            {
                "id": ws.id,
                "name": ws.name,
                "domain": ws.domain,
                "active": ws.id == self._active_id,
                "has_wp": bool(ws.wp_url and ws.wp_user),
            }
            for ws in self._workspaces.values()
        ]

    def update_rules(self, workspace_id: str, seo_rules: list[str] | None = None,
                     content_rules: list[str] | None = None) -> Workspace | None:
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return None
        if seo_rules is not None:
            ws.seo_rules = seo_rules
        if content_rules is not None:
            ws.content_rules = content_rules
        self._save()
        return ws

    def get_wp_credentials(self) -> tuple[str, str, str]:
        ws = self.active
        if ws and ws.wp_url and ws.wp_user:
            return ws.wp_url, ws.wp_user, ws.wp_password
        from app.config import get_settings
        s = get_settings()
        return s.wp_url, s.wp_user, s.wp_password

    def get_memory_prefix(self) -> str:
        ws = self.active
        if ws:
            return f"[{ws.slug}] "
        return ""


workspace_manager = WorkspaceManager()

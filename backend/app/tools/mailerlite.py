import logging
from typing import Any

import httpx

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

BASE_URL = "https://connect.mailerlite.com/api"


def _get_ml_key() -> str:
    return get_settings().mailerlite_api_key


def _headers(api_key: str = "") -> dict:
    key = api_key or _get_ml_key()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@registry.tool(
    name="ml_list_subscribers",
    description="List email subscribers from MailerLite. Can filter by status (active, unsubscribed, unconfirmed, bounced, junk).",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status", "default": "active", "enum": ["active", "unsubscribed", "unconfirmed", "bounced", "junk"]},
            "limit": {"type": "integer", "description": "Number of subscribers to return (max 100)", "default": 25},
            "search": {"type": "string", "description": "Search by email or name", "default": ""},
        },
    },
    category="email",
)
async def ml_list_subscribers(status: str = "active", limit: int = 25, search: str = "") -> dict:
    params: dict[str, Any] = {"filter[status]": status, "limit": min(limit, 100)}
    if search:
        params["filter[search]"] = search

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{BASE_URL}/subscribers", headers=_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()

    subscribers = data.get("data", [])
    return {
        "count": len(subscribers),
        "total": data.get("meta", {}).get("total", 0),
        "subscribers": [
            {
                "email": s.get("email", ""),
                "name": f"{s.get('fields', {}).get('name', '')} {s.get('fields', {}).get('last_name', '')}".strip(),
                "status": s.get("status", ""),
                "subscribed_at": s.get("subscribed_datetime", ""),
                "opens": s.get("stats", {}).get("opens_count", 0),
                "clicks": s.get("stats", {}).get("clicks_count", 0),
            }
            for s in subscribers
        ],
    }


@registry.tool(
    name="ml_add_subscriber",
    description="Add a new subscriber to MailerLite. Optionally add them to a specific group.",
    parameters={
        "type": "object",
        "properties": {
            "email": {"type": "string", "description": "Subscriber email address"},
            "name": {"type": "string", "description": "First name", "default": ""},
            "last_name": {"type": "string", "description": "Last name", "default": ""},
            "group_id": {"type": "string", "description": "Group ID to add subscriber to (optional)", "default": ""},
        },
        "required": ["email"],
    },
    category="email",
    requires_approval=True,
)
async def ml_add_subscriber(email: str = "", name: str = "", last_name: str = "", group_id: str = "") -> dict:
    payload: dict[str, Any] = {"email": email}
    fields: dict[str, str] = {}
    if name:
        fields["name"] = name
    if last_name:
        fields["last_name"] = last_name
    if fields:
        payload["fields"] = fields
    if group_id:
        payload["groups"] = [group_id]

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{BASE_URL}/subscribers", headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json().get("data", {})

    return {
        "status": "added",
        "email": data.get("email", email),
        "id": data.get("id", ""),
    }


@registry.tool(
    name="ml_list_groups",
    description="List all subscriber groups (segments/lists) in MailerLite.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 50},
        },
    },
    category="email",
)
async def ml_list_groups(limit: int = 50) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{BASE_URL}/groups", headers=_headers(), params={"limit": min(limit, 100)})
        resp.raise_for_status()
        data = resp.json()

    groups = data.get("data", [])
    return {
        "count": len(groups),
        "groups": [
            {
                "id": g.get("id", ""),
                "name": g.get("name", ""),
                "active_count": g.get("active_count", 0),
                "sent_count": g.get("sent_count", 0),
            }
            for g in groups
        ],
    }


@registry.tool(
    name="ml_create_campaign",
    description="Create a new email campaign in MailerLite. Creates as draft - won't send automatically.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Campaign name (internal reference)"},
            "subject": {"type": "string", "description": "Email subject line"},
            "content": {"type": "string", "description": "Email HTML content"},
            "from_name": {"type": "string", "description": "Sender name", "default": "PetHub Online"},
            "group_ids": {"type": "array", "items": {"type": "string"}, "description": "Group IDs to send to"},
        },
        "required": ["name", "subject", "content"],
    },
    category="email",
    requires_approval=True,
)
async def ml_create_campaign(name: str = "", subject: str = "", content: str = "",
                              from_name: str = "PetHub Online", group_ids: list[str] | None = None) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "type": "regular",
        "emails": [{
            "subject": subject,
            "from_name": from_name,
            "content": content,
        }],
    }
    if group_ids:
        payload["groups"] = group_ids

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{BASE_URL}/campaigns", headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json().get("data", {})

    return {
        "status": "draft_created",
        "campaign_id": data.get("id", ""),
        "name": name,
        "subject": subject,
        "note": "Campaign created as draft. Log in to MailerLite to review and send.",
    }


@registry.tool(
    name="ml_list_campaigns",
    description="List recent email campaigns from MailerLite with their stats (opens, clicks, etc.).",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by status", "default": "sent", "enum": ["draft", "ready", "sent"]},
            "limit": {"type": "integer", "default": 10},
        },
    },
    category="email",
)
async def ml_list_campaigns(status: str = "sent", limit: int = 10) -> dict:
    params = {"filter[status]": status, "limit": min(limit, 25)}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{BASE_URL}/campaigns", headers=_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()

    campaigns = data.get("data", [])
    return {
        "count": len(campaigns),
        "campaigns": [
            {
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "subject": c.get("emails", [{}])[0].get("subject", "") if c.get("emails") else "",
                "status": c.get("status", ""),
                "sent": c.get("stats", {}).get("sent", 0),
                "opens": c.get("stats", {}).get("opens_count", 0),
                "open_rate": c.get("stats", {}).get("open_rate", {}).get("float", 0),
                "clicks": c.get("stats", {}).get("clicks_count", 0),
                "click_rate": c.get("stats", {}).get("click_rate", {}).get("float", 0),
                "unsubscribes": c.get("stats", {}).get("unsubscribes_count", 0),
                "created_at": c.get("created_at", ""),
            }
            for c in campaigns
        ],
    }


@registry.tool(
    name="ml_subscriber_stats",
    description="Get overall subscriber statistics and growth from MailerLite.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="email",
)
async def ml_subscriber_stats() -> dict:
    results = {}

    async with httpx.AsyncClient(timeout=20.0) as client:
        for status in ["active", "unsubscribed", "unconfirmed", "bounced"]:
            resp = await client.get(
                f"{BASE_URL}/subscribers",
                headers=_headers(),
                params={"filter[status]": status, "limit": 1},
            )
            if resp.status_code == 200:
                results[status] = resp.json().get("meta", {}).get("total", 0)

    return {
        "active_subscribers": results.get("active", 0),
        "unsubscribed": results.get("unsubscribed", 0),
        "unconfirmed": results.get("unconfirmed", 0),
        "bounced": results.get("bounced", 0),
        "total": sum(results.values()),
    }

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def _get_wp_defaults() -> tuple[str, str, str]:
    try:
        from app.agents.workspace import workspace_manager
        return workspace_manager.get_wp_credentials()
    except Exception:
        s = get_settings()
        return s.wp_url, s.wp_user, s.wp_password


def _resolve(wp_url: str = "", wp_user: str = "", wp_password: str = "") -> tuple[str, str, str]:
    d = _get_wp_defaults()
    return (wp_url or d[0], wp_user or d[1], wp_password or d[2])


@registry.tool(
    name="wp_update_seo_meta",
    description="Update the SEO meta title, description, and focus keyword for a WordPress post or page using Rank Math. Use this when asked to update meta titles, meta descriptions, or SEO settings.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "The WordPress post or page ID to update"},
            "meta_title": {"type": "string", "description": "SEO meta title (recommended 50-60 chars)"},
            "meta_description": {"type": "string", "description": "SEO meta description (recommended 120-160 chars)"},
            "focus_keyword": {"type": "string", "description": "Primary focus keyword for the post"},
            "post_type": {"type": "string", "description": "Content type: posts or pages", "default": "posts"},
            "wp_url": {"type": "string", "default": ""},
            "wp_user": {"type": "string", "default": ""},
            "wp_password": {"type": "string", "default": ""},
        },
        "required": ["post_id"],
    },
    category="wordpress",
    requires_approval=True,
)
async def wp_update_seo_meta(post_id: int = 0, meta_title: str = "", meta_description: str = "",
                              focus_keyword: str = "", post_type: str = "",
                              wp_url: str = "", wp_user: str = "", wp_password: str = "") -> dict:
    wp_url, wp_user, wp_password = _resolve(wp_url, wp_user, wp_password)

    if not post_type:
        from app.tools.wordpress import _detect_post_type
        post_type = await _detect_post_type(wp_url, wp_user, wp_password, post_id)

    meta: dict[str, str] = {}
    if meta_title:
        meta["rank_math_title"] = meta_title
    if meta_description:
        meta["rank_math_description"] = meta_description
    if focus_keyword:
        meta["rank_math_focus_keyword"] = focus_keyword

    if not meta:
        return {"error": "No meta fields provided. Specify at least one of: meta_title, meta_description, focus_keyword"}

    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/{post_type}/{post_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url, auth=(wp_user, wp_password),
            json={"meta": meta},
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            data = response.json()
            saved_meta = data.get("meta", {})
            return {
                "post_id": post_id,
                "status": "updated",
                "meta_title": saved_meta.get("rank_math_title", meta_title),
                "meta_description": saved_meta.get("rank_math_description", meta_description),
                "focus_keyword": saved_meta.get("rank_math_focus_keyword", focus_keyword),
            }
        else:
            return {
                "post_id": post_id,
                "status": "failed",
                "error": response.text[:300],
                "status_code": response.status_code,
            }


@registry.tool(
    name="wp_get_seo_meta",
    description="Get the current SEO meta data (title, description, focus keyword) for a WordPress post or page.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "The WordPress post or page ID"},
            "post_type": {"type": "string", "description": "Content type: posts or pages", "default": "posts"},
            "wp_url": {"type": "string", "default": ""},
            "wp_user": {"type": "string", "default": ""},
            "wp_password": {"type": "string", "default": ""},
        },
        "required": ["post_id"],
    },
    category="wordpress",
)
async def wp_get_seo_meta(post_id: int = 0, post_type: str = "",
                           wp_url: str = "", wp_user: str = "", wp_password: str = "") -> dict:
    wp_url, wp_user, wp_password = _resolve(wp_url, wp_user, wp_password)

    if not post_type:
        from app.tools.wordpress import _detect_post_type
        post_type = await _detect_post_type(wp_url, wp_user, wp_password, post_id)

    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/{post_type}/{post_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, auth=(wp_user, wp_password))
        if response.status_code == 200:
            data = response.json()
            meta = data.get("meta", {})
            return {
                "post_id": post_id,
                "title": data.get("title", {}).get("rendered", ""),
                "rank_math_title": meta.get("rank_math_title", ""),
                "rank_math_description": meta.get("rank_math_description", ""),
                "rank_math_focus_keyword": meta.get("rank_math_focus_keyword", ""),
            }
        else:
            return {"post_id": post_id, "error": f"Could not fetch post: {response.status_code}"}

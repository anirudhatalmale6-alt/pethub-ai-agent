import logging
from typing import Any

import httpx

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def _get_wp_defaults() -> tuple[str, str, str]:
    s = get_settings()
    return s.wp_url, s.wp_user, s.wp_password


def _resolve(wp_url: str = "", wp_user: str = "", wp_password: str = "") -> tuple[str, str, str]:
    d = _get_wp_defaults()
    return (wp_url or d[0], wp_user or d[1], wp_password or d[2])


@registry.tool(
    name="wp_update_seo_meta",
    description="Update the SEO meta title, description, and focus keyword for a WordPress post or page using Rank Math. Use this when asked to update meta titles, meta descriptions, or SEO settings for any post or page.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "The WordPress post or page ID to update"},
            "meta_title": {"type": "string", "description": "SEO meta title (recommended 50-60 chars)"},
            "meta_description": {"type": "string", "description": "SEO meta description (recommended 120-160 chars)"},
            "focus_keyword": {"type": "string", "description": "Primary focus keyword for the post"},
            "wp_url": {"type": "string", "description": "WordPress URL (leave empty for default)", "default": ""},
            "wp_user": {"type": "string", "description": "WordPress user (leave empty for default)", "default": ""},
            "wp_password": {"type": "string", "description": "WordPress password (leave empty for default)", "default": ""},
        },
        "required": ["post_id"],
    },
    category="wordpress",
    requires_approval=True,
)
async def wp_update_seo_meta(post_id: int = 0, meta_title: str = "", meta_description: str = "",
                              focus_keyword: str = "", wp_url: str = "", wp_user: str = "",
                              wp_password: str = "") -> dict:
    wp_url, wp_user, wp_password = _resolve(wp_url, wp_user, wp_password)

    meta: dict[str, Any] = {}
    if meta_title:
        meta["rank_math_title"] = meta_title
    if meta_description:
        meta["rank_math_description"] = meta_description
    if focus_keyword:
        meta["rank_math_focus_keyword"] = focus_keyword

    if not meta:
        return {"error": "No meta fields provided. Specify at least one of: meta_title, meta_description, focus_keyword"}

    url = f"{wp_url.rstrip('/')}/wp-json/rankmath/v1/updateMeta"
    payload = {
        "objectID": post_id,
        "objectType": "post",
        "meta": meta,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url, auth=(wp_user, wp_password),
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            return {
                "post_id": post_id,
                "status": "updated",
                "meta_title": meta_title or "(unchanged)",
                "meta_description": meta_description or "(unchanged)",
                "focus_keyword": focus_keyword or "(unchanged)",
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
            "wp_url": {"type": "string", "description": "WordPress URL (leave empty for default)", "default": ""},
            "wp_user": {"type": "string", "description": "WordPress user (leave empty for default)", "default": ""},
            "wp_password": {"type": "string", "description": "WordPress password (leave empty for default)", "default": ""},
        },
        "required": ["post_id"],
    },
    category="wordpress",
)
async def wp_get_seo_meta(post_id: int = 0, wp_url: str = "", wp_user: str = "",
                           wp_password: str = "") -> dict:
    wp_url, wp_user, wp_password = _resolve(wp_url, wp_user, wp_password)

    url = f"{wp_url.rstrip('/')}/wp-json/rankmath/v1/getHead"
    params = {"url": f"{wp_url.rstrip('/')}/?p={post_id}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, auth=(wp_user, wp_password), params=params)

    # Fallback: read from post meta directly
    meta_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(meta_url, auth=(wp_user, wp_password))
        if response.status_code == 200:
            post = response.json()
            meta = post.get("meta", {})
            return {
                "post_id": post_id,
                "title": post.get("title", {}).get("rendered", ""),
                "rank_math_title": meta.get("rank_math_title", ""),
                "rank_math_description": meta.get("rank_math_description", ""),
                "rank_math_focus_keyword": meta.get("rank_math_focus_keyword", ""),
            }
        else:
            return {"post_id": post_id, "error": f"Could not fetch post: {response.status_code}"}

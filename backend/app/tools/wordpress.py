import logging
from typing import Any

import httpx

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def _get_wp_defaults() -> tuple[str, str, str]:
    s = get_settings()
    return s.wp_url, s.wp_user, s.wp_password


WP_PARAMS = {
    "type": "object",
    "properties": {
        "wp_url": {"type": "string", "description": "WordPress site URL. Leave empty to use the pre-configured default.", "default": ""},
        "wp_user": {"type": "string", "description": "WordPress username. Leave empty to use the pre-configured default.", "default": ""},
        "wp_password": {"type": "string", "description": "WordPress password. Leave empty to use the pre-configured default.", "default": ""},
    },
}


def _merge_params(base: dict, extra: dict) -> dict:
    merged = {**base}
    merged["properties"] = {**base["properties"], **extra.get("properties", {})}
    merged["required"] = list(set(base.get("required", []) + extra.get("required", [])))
    return merged


def _resolve_wp_creds(wp_url: str = "", wp_user: str = "", wp_password: str = "") -> tuple[str, str, str]:
    defaults = _get_wp_defaults()
    return (wp_url or defaults[0], wp_user or defaults[1], wp_password or defaults[2])


async def _wp_request(method: str, wp_url: str, wp_user: str, wp_password: str,
                      endpoint: str, data: dict | None = None, params: dict | None = None) -> dict[str, Any]:
    wp_url, wp_user, wp_password = _resolve_wp_creds(wp_url, wp_user, wp_password)
    url = f"{wp_url.rstrip('/')}/wp-json/{endpoint.lstrip('/')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=method, url=url, auth=(wp_user, wp_password),
            json=data, params=params,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()


@registry.tool(
    name="wp_list_posts",
    description="List WordPress posts with optional filters (status, category, search, per_page)",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "status": {"type": "string", "description": "Post status filter (publish, draft, pending, private)", "default": "publish"},
            "per_page": {"type": "integer", "description": "Number of posts to return (max 100)", "default": 10},
            "search": {"type": "string", "description": "Search term to filter posts"},
            "category": {"type": "integer", "description": "Category ID to filter by"},
            "page": {"type": "integer", "description": "Page number for pagination", "default": 1},
        },
    }),
    category="wordpress",
)
async def wp_list_posts(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                        status: str = "publish", per_page: int = 10, search: str = "",
                        category: int = 0, page: int = 1) -> dict:
    params: dict[str, Any] = {"status": status, "per_page": min(per_page, 100), "page": page}
    if search:
        params["search"] = search
    if category:
        params["categories"] = category

    posts = await _wp_request("GET", wp_url, wp_user, wp_password, "wp/v2/posts", params=params)
    return {
        "count": len(posts),
        "posts": [
            {"id": p["id"], "title": p["title"]["rendered"], "status": p["status"],
             "slug": p["slug"], "link": p["link"], "date": p["date"]}
            for p in posts
        ],
    }


@registry.tool(
    name="wp_create_post",
    description="Create a new WordPress post or page",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "title": {"type": "string", "description": "Post title"},
            "content": {"type": "string", "description": "Post content (HTML)"},
            "status": {"type": "string", "description": "Post status (publish, draft)", "default": "draft"},
            "post_type": {"type": "string", "description": "Content type: posts or pages", "default": "posts"},
            "categories": {"type": "array", "items": {"type": "integer"}, "description": "Category IDs"},
            "tags": {"type": "array", "items": {"type": "integer"}, "description": "Tag IDs"},
        },
        "required": ["title", "content"],
    }),
    category="wordpress",
    requires_approval=True,
)
async def wp_create_post(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                         title: str = "", content: str = "", status: str = "draft",
                         post_type: str = "posts", categories: list[int] | None = None,
                         tags: list[int] | None = None) -> dict:
    data: dict[str, Any] = {"title": title, "content": content, "status": status}
    if categories:
        data["categories"] = categories
    if tags:
        data["tags"] = tags

    endpoint = f"wp/v2/{post_type}"
    result = await _wp_request("POST", wp_url, wp_user, wp_password, endpoint, data=data)
    return {"id": result["id"], "title": result["title"]["rendered"],
            "status": result["status"], "link": result["link"]}


@registry.tool(
    name="wp_update_post",
    description="Update an existing WordPress post or page",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "post_id": {"type": "integer", "description": "Post/page ID to update"},
            "title": {"type": "string", "description": "New title (optional)"},
            "content": {"type": "string", "description": "New content (optional)"},
            "status": {"type": "string", "description": "New status (optional)"},
            "post_type": {"type": "string", "description": "Content type: posts or pages", "default": "posts"},
        },
        "required": ["post_id"],
    }),
    category="wordpress",
    requires_approval=True,
)
async def wp_update_post(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                         post_id: int = 0, title: str = "", content: str = "",
                         status: str = "", post_type: str = "posts") -> dict:
    data: dict[str, Any] = {}
    if title:
        data["title"] = title
    if content:
        data["content"] = content
    if status:
        data["status"] = status

    endpoint = f"wp/v2/{post_type}/{post_id}"
    result = await _wp_request("POST", wp_url, wp_user, wp_password, endpoint, data=data)
    return {"id": result["id"], "title": result["title"]["rendered"],
            "status": result["status"], "link": result["link"]}


@registry.tool(
    name="wp_delete_post",
    description="Delete a WordPress post or page (moves to trash)",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "post_id": {"type": "integer", "description": "Post/page ID to delete"},
            "post_type": {"type": "string", "description": "Content type: posts or pages", "default": "posts"},
            "force": {"type": "boolean", "description": "Permanently delete instead of trash", "default": False},
        },
        "required": ["post_id"],
    }),
    category="wordpress",
    requires_approval=True,
)
async def wp_delete_post(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                         post_id: int = 0, post_type: str = "posts", force: bool = False) -> dict:
    endpoint = f"wp/v2/{post_type}/{post_id}"
    params = {"force": force}
    result = await _wp_request("DELETE", wp_url, wp_user, wp_password, endpoint, params=params)
    return {"deleted": True, "id": post_id, "title": result.get("title", {}).get("rendered", "")}


@registry.tool(
    name="wp_list_pages",
    description="List WordPress pages",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "status": {"type": "string", "default": "publish"},
            "per_page": {"type": "integer", "default": 20},
            "search": {"type": "string"},
        },
    }),
    category="wordpress",
)
async def wp_list_pages(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                        status: str = "publish", per_page: int = 20, search: str = "") -> dict:
    params: dict[str, Any] = {"status": status, "per_page": min(per_page, 100)}
    if search:
        params["search"] = search

    pages = await _wp_request("GET", wp_url, wp_user, wp_password, "wp/v2/pages", params=params)
    return {
        "count": len(pages),
        "pages": [
            {"id": p["id"], "title": p["title"]["rendered"], "status": p["status"],
             "slug": p["slug"], "link": p["link"]}
            for p in pages
        ],
    }


@registry.tool(
    name="wp_upload_media",
    description="Upload media to WordPress (provide a URL to download from)",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "media_url": {"type": "string", "description": "URL of the file to upload"},
            "filename": {"type": "string", "description": "Filename for the uploaded media"},
            "alt_text": {"type": "string", "description": "Alt text for the media"},
        },
        "required": ["media_url", "filename"],
    }),
    category="wordpress",
)
async def wp_upload_media(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                          media_url: str = "", filename: str = "", alt_text: str = "") -> dict:
    wp_url, wp_user, wp_password = _resolve_wp_creds(wp_url, wp_user, wp_password)
    async with httpx.AsyncClient(timeout=60.0) as client:
        media_resp = await client.get(media_url)
        media_resp.raise_for_status()
        content_type = media_resp.headers.get("content-type", "image/jpeg")

        upload_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/media"
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        }
        resp = await client.post(
            upload_url, auth=(wp_user, wp_password),
            content=media_resp.content, headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()

    if alt_text:
        await _wp_request("POST", wp_url, wp_user, wp_password,
                          f"wp/v2/media/{result['id']}", data={"alt_text": alt_text})

    return {"id": result["id"], "url": result["source_url"], "filename": filename}


@registry.tool(
    name="wp_list_categories",
    description="List WordPress categories",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "per_page": {"type": "integer", "default": 100},
        },
    }),
    category="wordpress",
)
async def wp_list_categories(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                             per_page: int = 100) -> dict:
    cats = await _wp_request("GET", wp_url, wp_user, wp_password, "wp/v2/categories",
                             params={"per_page": min(per_page, 100)})
    return {
        "count": len(cats),
        "categories": [{"id": c["id"], "name": c["name"], "slug": c["slug"], "count": c["count"]} for c in cats],
    }


@registry.tool(
    name="wp_get_post",
    description="Get a single WordPress post or page by ID",
    parameters=_merge_params(WP_PARAMS, {
        "properties": {
            "post_id": {"type": "integer", "description": "Post/page ID"},
            "post_type": {"type": "string", "default": "posts"},
        },
        "required": ["post_id"],
    }),
    category="wordpress",
)
async def wp_get_post(wp_url: str = "", wp_user: str = "", wp_password: str = "",
                      post_id: int = 0, post_type: str = "posts") -> dict:
    result = await _wp_request("GET", wp_url, wp_user, wp_password, f"wp/v2/{post_type}/{post_id}")
    return {
        "id": result["id"],
        "title": result["title"]["rendered"],
        "content": result["content"]["rendered"][:2000],
        "status": result["status"],
        "slug": result["slug"],
        "link": result["link"],
        "date": result["date"],
        "modified": result["modified"],
    }

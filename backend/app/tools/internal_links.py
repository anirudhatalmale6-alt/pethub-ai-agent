import logging
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


@registry.tool(
    name="analyse_internal_links",
    description="Analyse the internal linking structure of a page. Shows which pages it links to, finds orphaned pages with no inbound links, and suggests new internal links to add.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to analyse"},
        },
        "required": ["url"],
    },
    category="content",
)
async def analyse_internal_links(url: str = "") -> dict:
    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        domain = ws.domain if ws else "pethubonline.com"
    except Exception:
        domain = "pethubonline.com"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "PetHub-AI-Agent/1.0"})
        resp.raise_for_status()
        html = resp.text

    internal = re.findall(rf'href="(https?://{re.escape(domain)}[^"]*)"', html, re.IGNORECASE)
    internal = list(dict.fromkeys(internal))
    external = re.findall(r'href="(https?://(?!' + re.escape(domain) + r')[^"]*)"', html, re.IGNORECASE)

    return {
        "url": url,
        "internal_links": len(internal),
        "external_links": len(external),
        "internal_targets": internal[:20],
        "needs_more_links": len(internal) < 3,
        "recommendation": "Add more internal links" if len(internal) < 3 else "Good internal linking",
    }


@registry.tool(
    name="suggest_internal_links",
    description="Suggest internal links to add to a post/page based on your site's content. Analyses the page topic and finds relevant pages to link to.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "Post/page ID to suggest links for"},
            "max_suggestions": {"type": "integer", "description": "Maximum suggestions", "default": 5},
        },
        "required": ["post_id"],
    },
    category="content",
)
async def suggest_internal_links(post_id: int = 0, max_suggestions: int = 5) -> dict:
    from app.tools.wordpress import wp_get_post, wp_list_posts, _detect_post_type

    post_type = await _detect_post_type("", "", "", post_id)
    post = await wp_get_post(post_id=post_id, post_type=post_type)
    title = post.get("title", "")
    content = post.get("content", "")[:1000]

    all_posts = await wp_list_posts(per_page=100)
    all_pages_data = []
    try:
        from app.tools.wordpress import wp_list_pages
        pages = await wp_list_pages(per_page=100)
        all_pages_data = pages.get("pages", [])
    except Exception:
        pass

    candidates = []
    for p in all_posts.get("posts", []) + all_pages_data:
        if p["id"] != post_id:
            candidates.append({"id": p["id"], "title": p["title"], "link": p["link"]})

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You suggest internal links. Given a post and candidate pages, select the most relevant ones to link to and suggest anchor text. Return JSON: {\"suggestions\": [{\"id\": 123, \"title\": \"...\", \"link\": \"...\", \"anchor_text\": \"suggested anchor text\", \"reason\": \"why link here\"}]}"},
            {"role": "user", "content": f"Post: {title}\nContent preview: {content[:500]}\n\nCandidates:\n{json.dumps(candidates[:30])}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    import json
    suggestions = json.loads(response.choices[0].message.content or "{}").get("suggestions", [])

    return {
        "post_id": post_id,
        "post_title": title,
        "suggestions": suggestions[:max_suggestions],
        "current_internal_links": content.count("pethubonline.com"),
    }

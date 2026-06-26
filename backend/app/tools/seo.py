import logging
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


async def _fetch_page(url: str) -> tuple[str, dict[str, str]]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "PetHub-AI-Agent/1.0"})
        resp.raise_for_status()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.text, headers


@registry.tool(
    name="seo_audit_page",
    description="Run a basic SEO audit on a webpage. Checks title, meta description, headings, images, links, schema markup, and common issues.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to audit"},
        },
        "required": ["url"],
    },
    category="seo",
)
async def seo_audit_page(url: str) -> dict:
    html, headers = await _fetch_page(url)
    html_lower = html.lower()

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    meta_desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
    if not meta_desc_match:
        meta_desc_match = re.search(r'<meta[^>]*content=["\'](.*?)["\'][^>]*name=["\']description["\']', html, re.IGNORECASE)
    meta_desc = meta_desc_match.group(1).strip() if meta_desc_match else ""

    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)

    imgs = re.findall(r"<img[^>]*>", html, re.IGNORECASE)
    imgs_no_alt = [img for img in imgs if 'alt=""' in img.lower() or "alt=''" in img.lower() or "alt" not in img.lower()]

    internal_links = len(re.findall(r'href=["\'][^"\']*' + re.escape(url.split("//")[1].split("/")[0]), html, re.IGNORECASE))
    external_links = len(re.findall(r'href=["\'](https?://)', html, re.IGNORECASE)) - internal_links

    has_canonical = bool(re.search(r'<link[^>]*rel=["\']canonical["\']', html, re.IGNORECASE))
    has_schema = "application/ld+json" in html_lower
    has_og = bool(re.search(r'<meta[^>]*property=["\']og:', html, re.IGNORECASE))
    has_robots = bool(re.search(r'<meta[^>]*name=["\']robots["\']', html, re.IGNORECASE))

    issues = []
    if not title:
        issues.append("Missing title tag")
    elif len(title) > 60:
        issues.append(f"Title too long ({len(title)} chars, recommended max 60)")
    elif len(title) < 20:
        issues.append(f"Title too short ({len(title)} chars, recommended min 20)")

    if not meta_desc:
        issues.append("Missing meta description")
    elif len(meta_desc) > 160:
        issues.append(f"Meta description too long ({len(meta_desc)} chars, recommended max 160)")
    elif len(meta_desc) < 70:
        issues.append(f"Meta description too short ({len(meta_desc)} chars, recommended min 70)")

    if not h1s:
        issues.append("Missing H1 tag")
    elif len(h1s) > 1:
        issues.append(f"Multiple H1 tags ({len(h1s)}), should have exactly 1")

    if imgs_no_alt:
        issues.append(f"{len(imgs_no_alt)} images missing alt text")

    if not has_canonical:
        issues.append("Missing canonical tag")

    if not has_schema:
        issues.append("No structured data (JSON-LD) found")

    if not has_og:
        issues.append("Missing Open Graph meta tags")

    score = 100
    score -= len(issues) * 8
    score = max(0, min(100, score))

    return {
        "url": url,
        "score": score,
        "title": title,
        "title_length": len(title),
        "meta_description": meta_desc[:200],
        "meta_description_length": len(meta_desc),
        "h1_count": len(h1s),
        "h1_text": [re.sub(r"<[^>]+>", "", h).strip() for h in h1s[:3]],
        "h2_count": len(h2s),
        "total_images": len(imgs),
        "images_missing_alt": len(imgs_no_alt),
        "internal_links": internal_links,
        "external_links": external_links,
        "has_canonical": has_canonical,
        "has_schema_markup": has_schema,
        "has_open_graph": has_og,
        "has_robots_meta": has_robots,
        "content_length": len(re.sub(r"<[^>]+>", "", html)),
        "issues": issues,
    }


@registry.tool(
    name="check_page_speed",
    description="Check basic page performance metrics (response time, page size, number of resources).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to check"},
        },
        "required": ["url"],
    },
    category="seo",
)
async def check_page_speed(url: str) -> dict:
    import time

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        start = time.monotonic()
        resp = await client.get(url, headers={"User-Agent": "PetHub-AI-Agent/1.0"})
        ttfb = round((time.monotonic() - start) * 1000)
        resp.raise_for_status()

    html = resp.text
    page_size_kb = round(len(html.encode()) / 1024, 1)

    css_count = len(re.findall(r'<link[^>]*rel=["\']stylesheet["\']', html, re.IGNORECASE))
    js_count = len(re.findall(r"<script[^>]*src=", html, re.IGNORECASE))
    img_count = len(re.findall(r"<img[^>]*src=", html, re.IGNORECASE))

    issues = []
    if ttfb > 1000:
        issues.append(f"Slow TTFB: {ttfb}ms (should be under 600ms)")
    if page_size_kb > 500:
        issues.append(f"Large page: {page_size_kb}KB (should be under 500KB)")
    if css_count > 10:
        issues.append(f"Too many CSS files: {css_count} (consider combining)")
    if js_count > 15:
        issues.append(f"Too many JS files: {js_count} (consider combining)")

    return {
        "url": url,
        "ttfb_ms": ttfb,
        "page_size_kb": page_size_kb,
        "css_files": css_count,
        "js_files": js_count,
        "images": img_count,
        "status_code": resp.status_code,
        "issues": issues,
    }


@registry.tool(
    name="check_broken_links",
    description="Check all links on a page for broken (404) or error responses.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to check links on"},
            "max_links": {"type": "integer", "description": "Maximum number of links to check", "default": 50},
        },
        "required": ["url"],
    },
    category="seo",
)
async def check_broken_links(url: str, max_links: int = 50) -> dict:
    html, _ = await _fetch_page(url)
    links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    unique_links = list(dict.fromkeys(links))[:max_links]

    broken = []
    ok_count = 0

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for link in unique_links:
            try:
                resp = await client.head(link, headers={"User-Agent": "PetHub-AI-Agent/1.0"})
                if resp.status_code >= 400:
                    broken.append({"url": link, "status": resp.status_code})
                else:
                    ok_count += 1
            except Exception:
                broken.append({"url": link, "status": "error"})

    return {
        "page_url": url,
        "total_links_checked": len(unique_links),
        "ok": ok_count,
        "broken": broken,
        "broken_count": len(broken),
    }

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

SITEMAP_DIR = os.environ.get("SITEMAP_DIR", "/app/sitemaps")
os.makedirs(SITEMAP_DIR, exist_ok=True)


def _get_domain() -> str:
    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        if ws:
            return ws.domain
    except Exception:
        pass
    return get_settings().wp_url.replace("https://", "").replace("http://", "").rstrip("/")


async def _fetch_sitemap_urls(base_url: str) -> list[str]:
    urls = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for sitemap_path in ["/sitemap_index.xml", "/sitemap.xml", "/wp-sitemap.xml"]:
            try:
                resp = await client.get(f"{base_url}{sitemap_path}")
                if resp.status_code == 200:
                    xml = resp.text
                    locs = re.findall(r"<loc>(.*?)</loc>", xml)
                    for loc in locs:
                        if loc.endswith(".xml"):
                            try:
                                sub_resp = await client.get(loc)
                                if sub_resp.status_code == 200:
                                    sub_locs = re.findall(r"<loc>(.*?)</loc>", sub_resp.text)
                                    urls.extend(sub_locs)
                            except Exception:
                                pass
                        else:
                            urls.append(loc)
                    if urls:
                        break
            except Exception:
                continue
    return list(dict.fromkeys(urls))


@registry.tool(
    name="crawl_site",
    description="Crawl the active workspace's website and build a complete URL map from the sitemap. Returns all pages and posts with their URLs. Use this to understand the full site structure.",
    parameters={
        "type": "object",
        "properties": {
            "max_urls": {"type": "integer", "description": "Maximum URLs to collect", "default": 500},
        },
    },
    category="site",
)
async def crawl_site(max_urls: int = 500) -> dict:
    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        base_url = f"https://{ws.domain}" if ws else get_settings().wp_url
    except Exception:
        base_url = get_settings().wp_url

    urls = await _fetch_sitemap_urls(base_url.rstrip("/"))
    urls = urls[:max_urls]

    pages = []
    posts = []
    other = []
    for url in urls:
        path = urlparse(url).path
        if any(cat in path for cat in ["/category/", "/tag/", "/author/"]):
            other.append(url)
        elif path.count("/") <= 2:
            pages.append(url)
        else:
            posts.append(url)

    domain = _get_domain()
    sitemap_path = os.path.join(SITEMAP_DIR, f"{domain.replace('.', '_')}_urls.json")
    with open(sitemap_path, "w") as f:
        json.dump({"domain": domain, "urls": urls, "count": len(urls)}, f)

    return {
        "domain": domain,
        "total_urls": len(urls),
        "pages": len(pages),
        "posts": len(posts),
        "other": len(other),
        "sample_pages": pages[:10],
        "sample_posts": posts[:10],
        "sitemap_saved": sitemap_path,
    }


@registry.tool(
    name="site_health_audit",
    description="Run a comprehensive health audit on the active workspace's website. Checks SEO, speed, broken links, and content quality across multiple pages. Returns a prioritised list of issues to fix.",
    parameters={
        "type": "object",
        "properties": {
            "max_pages": {"type": "integer", "description": "Maximum pages to audit (each takes a few seconds)", "default": 10},
            "check_type": {
                "type": "string",
                "description": "Type of check to run",
                "default": "all",
                "enum": ["all", "seo", "speed", "links"],
            },
        },
    },
    category="site",
)
async def site_health_audit(max_pages: int = 10, check_type: str = "all") -> dict:
    from app.tools.seo import seo_audit_page, check_page_speed, check_broken_links

    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        base_url = f"https://{ws.domain}" if ws else get_settings().wp_url
    except Exception:
        base_url = get_settings().wp_url

    domain = _get_domain()
    sitemap_path = os.path.join(SITEMAP_DIR, f"{domain.replace('.', '_')}_urls.json")

    if os.path.exists(sitemap_path):
        with open(sitemap_path) as f:
            data = json.load(f)
            urls = data.get("urls", [])
    else:
        urls = await _fetch_sitemap_urls(base_url.rstrip("/"))

    audit_urls = urls[:max_pages]
    results = []
    all_issues = []
    total_seo_score = 0
    total_speed_ms = 0

    for url in audit_urls:
        entry: dict[str, Any] = {"url": url}

        if check_type in ("all", "seo"):
            try:
                seo = await seo_audit_page(url=url)
                entry["seo_score"] = seo.get("score", 0)
                entry["seo_issues"] = seo.get("issues", [])
                total_seo_score += seo.get("score", 0)
                for issue in seo.get("issues", []):
                    all_issues.append({"url": url, "type": "seo", "issue": issue})
            except Exception as e:
                entry["seo_error"] = str(e)[:100]

        if check_type in ("all", "speed"):
            try:
                speed = await check_page_speed(url=url)
                entry["ttfb_ms"] = speed.get("ttfb_ms", 0)
                entry["page_size_kb"] = speed.get("page_size_kb", 0)
                total_speed_ms += speed.get("ttfb_ms", 0)
                for issue in speed.get("issues", []):
                    all_issues.append({"url": url, "type": "speed", "issue": issue})
            except Exception as e:
                entry["speed_error"] = str(e)[:100]

        if check_type in ("all", "links"):
            try:
                links = await check_broken_links(url=url, max_links=20)
                entry["broken_links"] = links.get("broken_count", 0)
                for bl in links.get("broken", []):
                    all_issues.append({"url": url, "type": "broken_link", "issue": f"Broken link: {bl['url']} ({bl['status']})"})
            except Exception as e:
                entry["links_error"] = str(e)[:100]

        results.append(entry)

    avg_seo = round(total_seo_score / max(len(audit_urls), 1))
    avg_speed = round(total_speed_ms / max(len(audit_urls), 1))

    critical = [i for i in all_issues if "missing" in i["issue"].lower() or "broken" in i["type"]]
    warnings = [i for i in all_issues if i not in critical]

    return {
        "domain": domain,
        "pages_audited": len(audit_urls),
        "average_seo_score": avg_seo,
        "average_ttfb_ms": avg_speed,
        "total_issues": len(all_issues),
        "critical_issues": len(critical),
        "warning_issues": len(warnings),
        "critical": critical[:20],
        "warnings": warnings[:20],
        "page_results": results,
    }


@registry.tool(
    name="get_site_urls",
    description="Get the stored URL map for the active workspace's website. Use after crawl_site to reference specific pages.",
    parameters={
        "type": "object",
        "properties": {
            "search": {"type": "string", "description": "Filter URLs containing this text", "default": ""},
            "limit": {"type": "integer", "description": "Max URLs to return", "default": 50},
        },
    },
    category="site",
)
async def get_site_urls(search: str = "", limit: int = 50) -> dict:
    domain = _get_domain()
    sitemap_path = os.path.join(SITEMAP_DIR, f"{domain.replace('.', '_')}_urls.json")

    if not os.path.exists(sitemap_path):
        return {"error": "No site map found. Run crawl_site first."}

    with open(sitemap_path) as f:
        data = json.load(f)
        urls = data.get("urls", [])

    if search:
        urls = [u for u in urls if search.lower() in u.lower()]

    return {
        "domain": domain,
        "total_urls": data.get("count", len(urls)),
        "filtered": len(urls[:limit]),
        "urls": urls[:limit],
    }


@registry.tool(
    name="visual_site_check",
    description="Take screenshots of multiple pages on the site and analyse them visually for UI issues, layout problems, and design consistency.",
    parameters={
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of URLs to screenshot and analyse. Leave empty to auto-select from site map.",
            },
            "max_pages": {"type": "integer", "description": "Max pages if auto-selecting", "default": 5},
        },
    },
    category="site",
)
async def visual_site_check(urls: list[str] | None = None, max_pages: int = 5) -> dict:
    from app.tools.vision import screenshot_and_analyse

    if not urls:
        domain = _get_domain()
        sitemap_path = os.path.join(SITEMAP_DIR, f"{domain.replace('.', '_')}_urls.json")
        if os.path.exists(sitemap_path):
            with open(sitemap_path) as f:
                data = json.load(f)
                urls = data.get("urls", [])[:max_pages]
        else:
            try:
                from app.agents.workspace import workspace_manager
                ws = workspace_manager.active
                base = f"https://{ws.domain}" if ws else get_settings().wp_url
            except Exception:
                base = get_settings().wp_url
            urls = [base]

    results = []
    for url in urls[:max_pages]:
        try:
            result = await screenshot_and_analyse(
                url=url,
                analysis_prompt="Check this page for: UI issues, layout problems, mobile responsiveness concerns, broken images, text readability, and overall design quality. Be specific about any issues found.",
            )
            results.append(result)
        except Exception as e:
            results.append({"url": url, "error": str(e)[:200]})

    issues_found = sum(1 for r in results if "issue" in str(r.get("analysis", "")).lower())

    return {
        "pages_checked": len(results),
        "issues_detected": issues_found,
        "results": results,
    }

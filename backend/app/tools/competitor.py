import logging
import re
from typing import Any

import httpx

from app.tools.registry import registry

logger = logging.getLogger(__name__)


@registry.tool(
    name="analyse_competitor",
    description="Analyse a competitor website. Crawls their sitemap, counts content, identifies topics, and compares against your site.",
    parameters={
        "type": "object",
        "properties": {
            "competitor_domain": {"type": "string", "description": "Competitor domain (e.g. 'allaboutdogfood.co.uk')"},
        },
        "required": ["competitor_domain"],
    },
    category="content",
)
async def analyse_competitor(competitor_domain: str = "") -> dict:
    base = f"https://{competitor_domain.replace('https://','').replace('http://','').rstrip('/')}"

    urls = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for path in ["/sitemap_index.xml", "/sitemap.xml", "/wp-sitemap.xml"]:
            try:
                resp = await client.get(f"{base}{path}")
                if resp.status_code == 200:
                    locs = re.findall(r"<loc>(.*?)</loc>", resp.text)
                    for loc in locs:
                        if loc.endswith(".xml"):
                            try:
                                sub = await client.get(loc)
                                urls.extend(re.findall(r"<loc>(.*?)</loc>", sub.text))
                            except Exception:
                                pass
                        else:
                            urls.append(loc)
                    if urls:
                        break
            except Exception:
                continue

    urls = list(dict.fromkeys(urls))

    topics = {}
    for url in urls:
        path = url.replace(base, "").strip("/")
        parts = path.split("/")
        if parts:
            cat = parts[0] if parts[0] else "homepage"
            topics[cat] = topics.get(cat, 0) + 1

    return {
        "competitor": competitor_domain,
        "total_urls": len(urls),
        "top_categories": dict(sorted(topics.items(), key=lambda x: x[1], reverse=True)[:15]),
        "sample_urls": urls[:15],
    }


@registry.tool(
    name="find_content_gaps",
    description="Compare your site against a competitor and find topics they cover that you don't. Identifies content opportunities.",
    parameters={
        "type": "object",
        "properties": {
            "competitor_domain": {"type": "string", "description": "Competitor domain to compare against"},
        },
        "required": ["competitor_domain"],
    },
    category="content",
)
async def find_content_gaps(competitor_domain: str = "") -> dict:
    from openai import AsyncOpenAI
    from app.config import get_settings

    competitor_data = await analyse_competitor(competitor_domain=competitor_domain)

    try:
        from app.tools.site_crawler import crawl_site
        our_data = await crawl_site(max_urls=200)
    except Exception:
        our_data = {"total_urls": 0, "sample_posts": []}

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "Compare two websites and identify content gaps. Return JSON: {\"gaps\": [{\"topic\": \"...\", \"competitor_has\": \"URL or description\", \"priority\": \"high/medium/low\", \"suggested_title\": \"...\"}], \"our_advantages\": [\"topics we cover better\"]}"},
            {"role": "user", "content": f"Our site URLs: {our_data.get('sample_posts', [])[:20]}\n\nCompetitor ({competitor_domain}) URLs: {competitor_data['sample_urls'][:20]}\nCompetitor categories: {competitor_data['top_categories']}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    import json
    gaps = json.loads(response.choices[0].message.content or "{}")

    return {
        "competitor": competitor_domain,
        "competitor_pages": competitor_data["total_urls"],
        "our_pages": our_data.get("total_urls", 0),
        "content_gaps": gaps.get("gaps", []),
        "our_advantages": gaps.get("our_advantages", []),
    }

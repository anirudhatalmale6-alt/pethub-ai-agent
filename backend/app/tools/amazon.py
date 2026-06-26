import logging
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.tools.registry import registry

logger = logging.getLogger(__name__)

AFFILIATE_TAG = "pethubonline-21"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _extract_asin(url: str) -> str:
    m = re.search(r'/(?:dp|product|gp/product)/([A-Z0-9]{10})', url)
    return m.group(1) if m else ""


def _affiliate_url(asin: str) -> str:
    return f"https://www.amazon.co.uk/dp/{asin}?tag={AFFILIATE_TAG}"


def _parse_product(html: str, asin: str = "") -> dict[str, Any]:
    title = ""
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', html, re.DOTALL)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()

    price = ""
    for pattern in [
        r'class="a-price-whole"[^>]*>([^<]+)',
        r'priceBlockBuyingPriceString"[^>]*>([^<]+)',
        r'"price":"([\d.]+)"',
    ]:
        m = re.search(pattern, html)
        if m:
            price = m.group(1).strip().rstrip('.')
            if not price.startswith('£'):
                price = f"£{price}"
            break

    rating = ""
    m = re.search(r'(\d+\.?\d*) out of 5', html)
    if m:
        rating = m.group(1)

    review_count = ""
    m = re.search(r'([\d,]+)\s*(?:ratings|reviews|global ratings)', html)
    if m:
        review_count = m.group(1).replace(',', '')

    image = ""
    for pattern in [
        r'"hiRes":"(https://[^"]+)"',
        r'"large":"(https://[^"]+)"',
        r'id="landingImage"[^>]*src="(https://[^"]+)"',
    ]:
        m = re.search(pattern, html)
        if m:
            image = m.group(1)
            break

    return {
        "asin": asin,
        "title": title,
        "price": price,
        "rating": rating,
        "review_count": review_count,
        "image": image,
        "url": _affiliate_url(asin),
    }


def _parse_search_results(html: str) -> list[dict]:
    products = []
    items = re.findall(r'data-asin="([A-Z0-9]{10})"', html)
    seen = set()

    for asin in items:
        if asin in seen or not asin:
            continue
        seen.add(asin)

        block_pattern = rf'data-asin="{asin}"(.*?)(?=data-asin="|$)'
        block_m = re.search(block_pattern, html, re.DOTALL)
        if not block_m:
            continue
        block = block_m.group(1)

        title = ""
        m = re.search(r'class="a-size-(?:base|medium|mini)[^"]*a-text-normal[^"]*"[^>]*>([^<]+)', block)
        if not m:
            m = re.search(r'class="a-link-normal[^"]*"[^>]*title="([^"]+)"', block)
        if m:
            title = m.group(1).strip()

        if not title:
            continue

        price = ""
        m = re.search(r'class="a-price-whole"[^>]*>([^<]+)', block)
        if m:
            price = f"£{m.group(1).strip().rstrip('.')}"

        rating = ""
        m = re.search(r'(\d+\.?\d*) out of 5', block)
        if m:
            rating = m.group(1)

        reviews = ""
        m = re.search(r'class="a-size-base[^"]*"[^>]*>(\d[\d,]*)</span>', block)
        if m:
            reviews = m.group(1).replace(',', '')

        image = ""
        m = re.search(r'<img[^>]*src="(https://m\.media-amazon\.com/images/[^"]+)"', block)
        if m:
            image = m.group(1)

        products.append({
            "asin": asin,
            "title": title[:120],
            "price": price,
            "rating": rating,
            "review_count": reviews,
            "image": image,
            "url": _affiliate_url(asin),
        })

        if len(products) >= 10:
            break

    return products


@registry.tool(
    name="amazon_search",
    description="Search Amazon UK for products. Returns product titles, prices, ratings, review counts, images, and affiliate links. Use for building comparison tables and product roundups.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (e.g. 'dog beds medium')"},
            "max_results": {"type": "integer", "description": "Maximum products to return (max 10)", "default": 5},
        },
        "required": ["query"],
    },
    category="amazon",
)
async def amazon_search(query: str = "", max_results: int = 5) -> dict:
    url = f"https://www.amazon.co.uk/s?k={quote_plus(query)}&tag={AFFILIATE_TAG}"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()

    products = _parse_search_results(resp.text)[:max_results]

    return {
        "query": query,
        "count": len(products),
        "products": products,
    }


@registry.tool(
    name="amazon_product_details",
    description="Get detailed information about a specific Amazon UK product by URL or ASIN. Returns title, price, rating, review count, image, and affiliate link.",
    parameters={
        "type": "object",
        "properties": {
            "url_or_asin": {"type": "string", "description": "Amazon product URL or ASIN (e.g. 'B08XYZ123' or 'https://amazon.co.uk/dp/B08XYZ123')"},
        },
        "required": ["url_or_asin"],
    },
    category="amazon",
)
async def amazon_product_details(url_or_asin: str = "") -> dict:
    asin = _extract_asin(url_or_asin) if '/' in url_or_asin else url_or_asin.strip()
    if not asin:
        return {"error": "Could not extract ASIN from the provided URL or value"}

    url = f"https://www.amazon.co.uk/dp/{asin}?tag={AFFILIATE_TAG}"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()

    product = _parse_product(resp.text, asin)
    return product


@registry.tool(
    name="amazon_build_comparison",
    description="Search Amazon UK and build a ready-to-use HTML comparison table for WordPress. Includes product images, titles, prices, ratings, and affiliate buy links.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (e.g. 'best cat water fountains')"},
            "count": {"type": "integer", "description": "Number of products in the table (3-5 recommended)", "default": 5},
            "table_title": {"type": "string", "description": "Title for the comparison table", "default": ""},
        },
        "required": ["query"],
    },
    category="amazon",
)
async def amazon_build_comparison(query: str = "", count: int = 5, table_title: str = "") -> dict:
    url = f"https://www.amazon.co.uk/s?k={quote_plus(query)}&tag={AFFILIATE_TAG}"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()

    products = _parse_search_results(resp.text)[:count]

    if not products:
        return {"error": "No products found", "query": query}

    title = table_title or f"Best {query.title()} - Amazon UK"

    rows = ""
    for p in products:
        stars = ""
        if p["rating"]:
            full = int(float(p["rating"]))
            stars = "★" * full + "☆" * (5 - full)
        reviews = f"({p['review_count']} reviews)" if p["review_count"] else ""
        img = f'<img src="{p["image"]}" alt="{p["title"][:60]}" style="width:80px;height:80px;object-fit:contain;" loading="lazy">' if p["image"] else ""

        rows += f"""<tr>
<td style="text-align:center;padding:12px">{img}</td>
<td style="padding:12px"><strong>{p["title"][:80]}</strong></td>
<td style="text-align:center;padding:12px;white-space:nowrap"><strong>{p["price"]}</strong></td>
<td style="text-align:center;padding:12px;color:#f59e0b">{stars}<br><small>{reviews}</small></td>
<td style="text-align:center;padding:12px"><a href="{p["url"]}" target="_blank" rel="nofollow sponsored" style="background:#046bd2;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none;font-weight:600;font-size:13px;display:inline-block">View on Amazon</a></td>
</tr>
"""

    html = f"""<h2>{title}</h2>
<div style="overflow-x:auto">
<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0">
<thead>
<tr style="background:#f8fafc">
<th style="padding:12px;text-align:center">Image</th>
<th style="padding:12px;text-align:left">Product</th>
<th style="padding:12px;text-align:center">Price</th>
<th style="padding:12px;text-align:center">Rating</th>
<th style="padding:12px;text-align:center">Buy</th>
</tr>
</thead>
<tbody>
{rows}</tbody>
</table>
</div>
<p style="font-size:12px;color:#94a3b8;margin-top:8px"><em>Prices and availability correct at time of writing. As an Amazon Associate, PetHub Online earns from qualifying purchases.</em></p>"""

    return {
        "query": query,
        "product_count": len(products),
        "html": html,
        "products": products,
    }

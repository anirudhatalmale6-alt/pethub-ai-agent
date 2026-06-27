import json
import logging
import re

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


@registry.tool(
    name="audit_schema",
    description="Audit a page for missing structured data (JSON-LD schema markup). Checks for Article, FAQ, Product, HowTo, and other schema types. Suggests what to add.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "WordPress post/page ID to audit"},
        },
        "required": ["post_id"],
    },
    category="content",
)
async def audit_schema(post_id: int = 0) -> dict:
    from app.tools.wordpress import wp_get_post, _detect_post_type

    post_type = await _detect_post_type("", "", "", post_id)
    post = await wp_get_post(post_id=post_id, post_type=post_type)
    content = post.get("content", "")
    title = post.get("title", "")

    existing = re.findall(r'application/ld\+json["\s>]*(\{.*?\})\s*</script>', content, re.DOTALL | re.IGNORECASE)

    found_types = []
    for schema_str in existing:
        try:
            schema = json.loads(schema_str)
            found_types.append(schema.get("@type", "Unknown"))
        except Exception:
            pass

    has_faq = bool(re.search(r'frequently asked|faq', content, re.IGNORECASE))
    has_howto = bool(re.search(r'how to|step \d|step-by-step', content, re.IGNORECASE))
    has_products = bool(re.search(r'amazon|buy|price|£', content, re.IGNORECASE))
    has_comparison = '<table' in content.lower()

    missing = []
    if "Article" not in found_types and "BlogPosting" not in found_types:
        missing.append({"type": "Article", "priority": "high", "reason": "Every post should have Article schema"})
    if has_faq and "FAQPage" not in found_types:
        missing.append({"type": "FAQPage", "priority": "high", "reason": "FAQ section detected but no FAQ schema"})
    if has_howto and "HowTo" not in found_types:
        missing.append({"type": "HowTo", "priority": "medium", "reason": "How-to content detected"})
    if has_products and "Product" not in found_types:
        missing.append({"type": "Product", "priority": "medium", "reason": "Product mentions detected"})
    if has_comparison and "ItemList" not in found_types:
        missing.append({"type": "ItemList", "priority": "low", "reason": "Comparison table could use ItemList schema"})

    return {
        "post_id": post_id,
        "title": title,
        "existing_schema": found_types,
        "missing_schema": missing,
        "has_faq_content": has_faq,
        "has_howto_content": has_howto,
        "has_products": has_products,
        "score": max(0, 100 - (len(missing) * 20)),
    }


@registry.tool(
    name="generate_schema",
    description="Generate JSON-LD structured data for a WordPress post. Creates FAQ, Article, HowTo, or Product schema based on the content.",
    parameters={
        "type": "object",
        "properties": {
            "post_id": {"type": "integer", "description": "WordPress post/page ID"},
            "schema_type": {"type": "string", "description": "Type of schema to generate", "enum": ["FAQ", "Article", "HowTo", "Product"]},
        },
        "required": ["post_id", "schema_type"],
    },
    category="content",
    requires_approval=True,
)
async def generate_schema(post_id: int = 0, schema_type: str = "FAQ") -> dict:
    from app.tools.wordpress import wp_get_post, _detect_post_type

    post_type = await _detect_post_type("", "", "", post_id)
    post = await wp_get_post(post_id=post_id, post_type=post_type)
    content = post.get("content", "")
    title = post.get("title", "")

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": f"Generate valid JSON-LD {schema_type} schema for this page. Return ONLY the JSON-LD object, no script tags."},
            {"role": "user", "content": f"Title: {title}\nURL: {post.get('link', '')}\nContent:\n{content[:3000]}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    schema = json.loads(response.choices[0].message.content or "{}")

    return {
        "post_id": post_id,
        "schema_type": schema_type,
        "schema": schema,
        "script_tag": f'<script type="application/ld+json">{json.dumps(schema, indent=2)}</script>',
    }

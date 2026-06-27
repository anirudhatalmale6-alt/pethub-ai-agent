import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

WRITER_PROMPT = """You are a professional UK pet content writer for PetHub Online (pethubonline.com).

Write a complete, publish-ready blog post/article following these rules:

{workspace_rules}

ARTICLE STRUCTURE:
1. H3 "At a Glance" box with 4-5 key takeaways as bullet points
2. H2 introduction section (2-3 paragraphs)
3. 4-6 H2 topic sections (2-3 paragraphs each, detailed and informative)
4. H2 Comparison table section (if products mentioned) - use HTML table with images, names, prices, ratings, buy links
5. H2 "Frequently Asked Questions" - 5-8 Q&A pairs
6. H2 "Key Terms" - define 4-6 important terms
7. H2 "Sources" - cite 3-5 credible sources

REQUIREMENTS:
- Minimum 2000 words
- British English throughout
- Write for UK pet owners aged 25-45
- Friendly, authoritative, helpful tone
- Include at least 3 internal links to pethubonline.com pages
- All Amazon links must use affiliate tag: {affiliate_tag}
- Include FAQ schema-ready Q&A format
- Every image mention should include alt text suggestion

Return the complete HTML content ready for WordPress. No markdown - pure HTML with proper heading tags."""


@registry.tool(
    name="write_article",
    description="Write a complete, publish-ready 2000+ word article with proper structure, internal links, comparison tables, FAQ, and sources. Follows the workspace's content rules automatically.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Article topic (e.g. 'Best Cat Litter Trays UK 2026')"},
            "focus_keyword": {"type": "string", "description": "Primary SEO keyword to target"},
            "article_type": {
                "type": "string",
                "description": "Type of article",
                "default": "guide",
                "enum": ["guide", "comparison", "how_to", "listicle", "review"],
            },
            "word_count": {"type": "integer", "description": "Target word count", "default": 2000},
        },
        "required": ["topic", "focus_keyword"],
    },
    category="content",
    requires_approval=True,
)
async def write_article(topic: str = "", focus_keyword: str = "",
                         article_type: str = "guide", word_count: int = 2000) -> dict:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    workspace_rules = ""
    affiliate_tag = "pethubonline-21"
    try:
        from app.agents.workspace import workspace_manager
        ws = workspace_manager.active
        if ws:
            workspace_rules = "\n".join(ws.content_rules + ws.seo_rules)
            affiliate_tag = ws.affiliate_tag or affiliate_tag
    except Exception:
        pass

    improvement_rules = ""
    try:
        from app.agents.feedback import feedback_engine
        rules = await feedback_engine.get_improvement_rules("content_creation")
        if rules:
            improvement_rules = "\nLEARNED RULES:\n" + "\n".join(f"- {r}" for r in rules[:10])
    except Exception:
        pass

    prompt = WRITER_PROMPT.format(
        workspace_rules=workspace_rules + improvement_rules,
        affiliate_tag=affiliate_tag,
    )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Write a complete {article_type} article about: {topic}\n\nFocus keyword: {focus_keyword}\nTarget length: {word_count}+ words\nMake it comprehensive, authoritative, and ready to publish."},
        ],
        temperature=0.4,
        max_tokens=8000,
    )

    content = response.choices[0].message.content or ""
    word_count_actual = len(content.split())

    headings = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', content, re.IGNORECASE | re.DOTALL)
    heading_list = [re.sub(r'<[^>]+>', '', h).strip() for h in headings]

    has_faq = bool(re.search(r'frequently asked|faq', content, re.IGNORECASE))
    has_table = '<table' in content.lower()
    internal_links = len(re.findall(r'pethubonline\.com', content))
    affiliate_links = content.count(affiliate_tag)

    return {
        "topic": topic,
        "focus_keyword": focus_keyword,
        "word_count": word_count_actual,
        "headings": heading_list,
        "has_faq": has_faq,
        "has_comparison_table": has_table,
        "internal_links": internal_links,
        "affiliate_links": affiliate_links,
        "content": content,
        "ready_to_publish": word_count_actual >= 1500 and has_faq and len(heading_list) >= 6,
    }


@registry.tool(
    name="write_and_publish",
    description="Write a complete article AND create it as a draft post in WordPress with SEO meta set. One-step content creation.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Article topic"},
            "focus_keyword": {"type": "string", "description": "Primary SEO keyword"},
            "category_id": {"type": "integer", "description": "WordPress category ID (optional)", "default": 0},
        },
        "required": ["topic", "focus_keyword"],
    },
    category="content",
    requires_approval=True,
)
async def write_and_publish(topic: str = "", focus_keyword: str = "",
                             category_id: int = 0) -> dict:
    article = await write_article(topic=topic, focus_keyword=focus_keyword)

    if not article.get("content"):
        return {"error": "Article generation failed"}

    from app.tools.wordpress import wp_create_post
    post = await wp_create_post(title=topic, content=article["content"], status="draft",
                                 categories=[category_id] if category_id else None)

    if post.get("id"):
        from app.tools.wp_seo import wp_update_seo_meta
        meta_title = f"{topic} | PetHub Online"
        meta_desc = f"Discover {topic.lower()}. Expert guide with comparisons, reviews, and tips for UK pet owners."
        await wp_update_seo_meta(post_id=post["id"], meta_title=meta_title[:60],
                                  meta_description=meta_desc[:155], focus_keyword=focus_keyword)

    return {
        "article_word_count": article["word_count"],
        "post_id": post.get("id"),
        "post_link": post.get("link"),
        "status": "draft",
        "seo_set": True,
        "message": f"Article written ({article['word_count']} words) and published as draft. Review at {post.get('link', 'WordPress admin')}.",
    }

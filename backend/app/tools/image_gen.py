import logging
import os
import uuid

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)


@registry.tool(
    name="generate_image",
    description="Generate a custom image using DALL-E. Creates featured images, infographics, comparison graphics, or any visual content. Returns the image URL.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Image description (be specific - include style, colours, composition)"},
            "size": {"type": "string", "description": "Image size", "default": "1792x1024", "enum": ["1024x1024", "1792x1024", "1024x1792"]},
            "style": {"type": "string", "description": "Image style", "default": "natural", "enum": ["natural", "vivid"]},
        },
        "required": ["prompt"],
    },
    category="content",
    requires_approval=True,
)
async def generate_image(prompt: str = "", size: str = "1792x1024", style: str = "natural") -> dict:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            style=style,
            n=1,
        )

        image_url = response.data[0].url
        revised_prompt = response.data[0].revised_prompt

        return {
            "image_url": image_url,
            "revised_prompt": revised_prompt,
            "size": size,
            "style": style,
            "note": "Image URL expires after 1 hour. Upload to WordPress using wp_upload_media to save permanently.",
        }

    except Exception as e:
        error_msg = str(e)
        if "billing" in error_msg.lower() or "quota" in error_msg.lower():
            return {"error": "DALL-E requires billing to be set up on your OpenAI account. Check platform.openai.com/billing."}
        return {"error": f"Image generation failed: {error_msg}"}


@registry.tool(
    name="generate_featured_image",
    description="Generate a featured image for a blog post and upload it to WordPress. One-step image creation.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Blog post topic (used to create relevant image)"},
            "post_id": {"type": "integer", "description": "WordPress post ID to set as featured image (optional)", "default": 0},
        },
        "required": ["topic"],
    },
    category="content",
    requires_approval=True,
)
async def generate_featured_image(topic: str = "", post_id: int = 0) -> dict:
    prompt = f"Professional blog featured image for an article about {topic}. Clean, modern photography style. Bright, welcoming colours. No text overlay. High quality, editorial feel. Pet care and lifestyle theme."

    result = await generate_image(prompt=prompt, size="1792x1024", style="natural")

    if result.get("error"):
        return result

    image_url = result.get("image_url", "")
    if not image_url:
        return {"error": "No image URL returned"}

    from app.tools.wordpress import wp_upload_media
    slug = topic.lower().replace(" ", "-")[:40]
    upload = await wp_upload_media(
        media_url=image_url,
        filename=f"{slug}-featured.png",
        alt_text=topic,
    )

    return {
        "image_id": upload.get("id"),
        "image_url": upload.get("url"),
        "post_id": post_id,
        "message": f"Featured image generated and uploaded to WordPress (ID: {upload.get('id')}).",
    }

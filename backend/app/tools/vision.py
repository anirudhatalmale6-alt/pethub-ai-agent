import asyncio
import base64
import logging
import os
import tempfile
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = os.environ.get("SCREENSHOTS_DIR", "/app/screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


async def _capture_screenshot(url: str, viewport_width: int = 1280,
                               viewport_height: int = 720, full_page: bool = False,
                               wait_seconds: int = 3) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": viewport_width, "height": viewport_height})

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(wait_seconds)

        filename = f"screenshot_{hash(url) & 0xFFFFFFFF:08x}.png"
        filepath = os.path.join(SCREENSHOTS_DIR, filename)

        await page.screenshot(path=filepath, full_page=full_page)
        await browser.close()

    return filepath


async def _analyse_image(image_path: str, prompt: str) -> str:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_data}"},
                    },
                ],
            }
        ],
        max_tokens=2000,
    )

    return response.choices[0].message.content or ""


@registry.tool(
    name="screenshot_and_analyse",
    description="Take a screenshot of a URL and analyse it with AI vision. Use for diagnosing UI issues, checking page layout, reviewing SEO elements, or inspecting any webpage.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to screenshot (e.g. https://example.com)"},
            "analysis_prompt": {
                "type": "string",
                "description": "What to analyse in the screenshot (e.g. 'Check for UI issues', 'Review SEO elements', 'Identify layout problems')",
                "default": "Analyse this webpage screenshot. Identify any UI issues, layout problems, broken elements, or areas for improvement. Comment on the overall design quality and user experience.",
            },
            "viewport_width": {"type": "integer", "description": "Browser viewport width in pixels", "default": 1280},
            "viewport_height": {"type": "integer", "description": "Browser viewport height in pixels", "default": 720},
            "full_page": {"type": "boolean", "description": "Capture the full scrollable page (not just viewport)", "default": False},
        },
        "required": ["url"],
    },
    category="vision",
)
async def screenshot_and_analyse(url: str, analysis_prompt: str = "",
                                  viewport_width: int = 1280, viewport_height: int = 720,
                                  full_page: bool = False) -> dict:
    if not analysis_prompt:
        analysis_prompt = "Analyse this webpage screenshot. Identify any UI issues, layout problems, broken elements, or areas for improvement. Comment on the overall design quality and user experience."

    filepath = await _capture_screenshot(url, viewport_width, viewport_height, full_page)
    analysis = await _analyse_image(filepath, analysis_prompt)

    return {
        "url": url,
        "screenshot_path": filepath,
        "analysis": analysis,
        "viewport": f"{viewport_width}x{viewport_height}",
    }


@registry.tool(
    name="screenshot_compare",
    description="Take screenshots of two URLs and compare them. Useful for before/after comparisons, competitor analysis, or staging vs production checks.",
    parameters={
        "type": "object",
        "properties": {
            "url_a": {"type": "string", "description": "First URL to screenshot"},
            "url_b": {"type": "string", "description": "Second URL to screenshot"},
            "comparison_prompt": {
                "type": "string",
                "description": "What to compare between the two screenshots",
                "default": "Compare these two webpage screenshots. Note differences in layout, content, design, and functionality.",
            },
        },
        "required": ["url_a", "url_b"],
    },
    category="vision",
)
async def screenshot_compare(url_a: str, url_b: str, comparison_prompt: str = "") -> dict:
    if not comparison_prompt:
        comparison_prompt = "Compare these two webpage screenshots. Note differences in layout, content, design, and functionality. Highlight any issues or improvements."

    path_a, path_b = await asyncio.gather(
        _capture_screenshot(url_a),
        _capture_screenshot(url_b),
    )

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    with open(path_a, "rb") as f:
        img_a = base64.b64encode(f.read()).decode("utf-8")
    with open(path_b, "rb") as f:
        img_b = base64.b64encode(f.read()).decode("utf-8")

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{comparison_prompt}\n\nImage 1: {url_a}\nImage 2: {url_b}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_a}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b}"}},
                ],
            }
        ],
        max_tokens=2000,
    )

    analysis = response.choices[0].message.content or ""
    return {
        "url_a": url_a,
        "url_b": url_b,
        "screenshot_a": path_a,
        "screenshot_b": path_b,
        "comparison": analysis,
    }


@registry.tool(
    name="analyse_uploaded_image",
    description="Analyse an image that has already been saved locally (e.g. a dashboard screenshot, design mockup, or error screenshot).",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Path to the local image file"},
            "analysis_prompt": {
                "type": "string",
                "description": "What to analyse in the image",
                "default": "Analyse this image and describe what you see. Identify any issues or noteworthy elements.",
            },
        },
        "required": ["image_path"],
    },
    category="vision",
)
async def analyse_uploaded_image(image_path: str, analysis_prompt: str = "") -> dict:
    if not analysis_prompt:
        analysis_prompt = "Analyse this image and describe what you see. Identify any issues or noteworthy elements."

    if not os.path.exists(image_path):
        return {"error": f"File not found: {image_path}"}

    analysis = await _analyse_image(image_path, analysis_prompt)
    return {"image_path": image_path, "analysis": analysis}

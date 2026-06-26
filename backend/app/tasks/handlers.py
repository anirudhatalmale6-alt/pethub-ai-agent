import logging
from typing import Any

from app.tasks.queue import TaskQueue, task_queue
from app.tools.registry import registry

logger = logging.getLogger(__name__)


async def bulk_wp_operation(job_id: str, payload: dict[str, Any], queue: TaskQueue) -> dict:
    """Execute multiple WordPress operations in sequence with progress tracking."""
    operations = payload.get("operations", [])
    wp_url = payload.get("wp_url", "")
    wp_user = payload.get("wp_user", "")
    wp_password = payload.get("wp_password", "")

    if not operations:
        return {"error": "No operations provided"}

    results = []
    total = len(operations)

    for i, op in enumerate(operations):
        tool_name = op.get("tool")
        arguments = op.get("arguments", {})
        arguments.update({"wp_url": wp_url, "wp_user": wp_user, "wp_password": wp_password})

        await queue.update_progress(
            job_id,
            progress=int((i / total) * 100),
            message=f"Executing {tool_name} ({i + 1}/{total})",
        )

        try:
            result = await registry.execute(tool_name, arguments)
            results.append({"tool": tool_name, "status": "success", "result": result})
        except Exception as e:
            results.append({"tool": tool_name, "status": "error", "error": str(e)})

    succeeded = sum(1 for r in results if r["status"] == "success")
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": total - succeeded,
        "results": results,
    }


async def full_site_seo_audit(job_id: str, payload: dict[str, Any], queue: TaskQueue) -> dict:
    """Run SEO audit across multiple pages of a site."""
    from app.tools.seo import seo_audit_page, check_page_speed, check_broken_links

    urls = payload.get("urls", [])
    if not urls:
        return {"error": "No URLs provided"}

    results = []
    total = len(urls)

    for i, url in enumerate(urls):
        await queue.update_progress(
            job_id,
            progress=int((i / total) * 100),
            message=f"Auditing {url} ({i + 1}/{total})",
        )

        try:
            audit = await seo_audit_page(url=url)
            speed = await check_page_speed(url=url)
            results.append({
                "url": url,
                "seo_score": audit.get("score", 0),
                "seo_issues": audit.get("issues", []),
                "ttfb_ms": speed.get("ttfb_ms", 0),
                "page_size_kb": speed.get("page_size_kb", 0),
                "speed_issues": speed.get("issues", []),
            })
        except Exception as e:
            results.append({"url": url, "error": str(e)})

    avg_score = 0
    scored = [r for r in results if "seo_score" in r]
    if scored:
        avg_score = round(sum(r["seo_score"] for r in scored) / len(scored))

    all_issues = []
    for r in results:
        for issue in r.get("seo_issues", []):
            all_issues.append({"url": r["url"], "issue": issue})

    return {
        "pages_audited": total,
        "average_seo_score": avg_score,
        "total_issues": len(all_issues),
        "issues": all_issues[:50],
        "page_results": results,
    }


async def bulk_screenshot_audit(job_id: str, payload: dict[str, Any], queue: TaskQueue) -> dict:
    """Take screenshots and run vision analysis on multiple pages."""
    from app.tools.vision import screenshot_and_analyse

    urls = payload.get("urls", [])
    analysis_prompt = payload.get("analysis_prompt", "")

    if not urls:
        return {"error": "No URLs provided"}

    results = []
    total = len(urls)

    for i, url in enumerate(urls):
        await queue.update_progress(
            job_id,
            progress=int((i / total) * 100),
            message=f"Screenshotting {url} ({i + 1}/{total})",
        )

        try:
            result = await screenshot_and_analyse(url=url, analysis_prompt=analysis_prompt)
            results.append(result)
        except Exception as e:
            results.append({"url": url, "error": str(e)})

    return {"pages_analysed": total, "results": results}


def register_handlers() -> None:
    task_queue.register_handler("bulk_wp_operation", bulk_wp_operation)
    task_queue.register_handler("full_site_seo_audit", full_site_seo_audit)
    task_queue.register_handler("bulk_screenshot_audit", bulk_screenshot_audit)

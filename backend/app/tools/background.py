import logging
from typing import Any

from app.tools.registry import registry
from app.tasks.queue import task_queue

logger = logging.getLogger(__name__)


@registry.tool(
    name="run_background_task",
    description="Queue a long-running task to execute in the background. Use for bulk operations, full-site audits, or anything that would take more than a few seconds. Returns a job ID you can use to check progress.",
    parameters={
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "description": "Type of background task",
                "enum": ["bulk_wp_operation", "full_site_seo_audit", "bulk_screenshot_audit"],
            },
            "payload": {
                "type": "object",
                "description": "Task-specific parameters. For bulk_wp_operation: {operations: [{tool, arguments}], wp_url, wp_user, wp_password}. For full_site_seo_audit: {urls: [...]}. For bulk_screenshot_audit: {urls: [...], analysis_prompt: '...'}",
            },
        },
        "required": ["task_type", "payload"],
    },
    category="system",
    requires_approval=True,
)
async def run_background_task(task_type: str, payload: dict[str, Any]) -> dict:
    job = await task_queue.enqueue(task_type=task_type, payload=payload)
    return {
        "job_id": job.id,
        "task_type": task_type,
        "status": "queued",
        "message": f"Background task '{task_type}' has been queued. Use the job ID to check progress.",
    }


@registry.tool(
    name="check_job_status",
    description="Check the status and progress of a background job.",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID returned from run_background_task"},
        },
        "required": ["job_id"],
    },
    category="system",
)
async def check_job_status(job_id: str) -> dict:
    job = await task_queue.get_job(job_id)
    if not job:
        return {"error": f"Job {job_id} not found"}

    result: dict[str, Any] = {
        "job_id": job.id,
        "task_type": job.task_type,
        "status": job.status,
        "progress": job.progress,
        "progress_message": job.progress_message,
        "attempt": job.attempt,
    }

    if job.result:
        result["result"] = job.result
    if job.error:
        result["error"] = job.error

    return result

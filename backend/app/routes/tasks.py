import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.models.models import User
from app.utils.auth import get_current_user
from app.tasks.queue import task_queue

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class EnqueueRequest(BaseModel):
    task_type: str
    payload: dict = {}
    max_retries: int = 3


class JobResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress: int
    progress_message: str
    result: dict | None
    error: str | None
    attempt: int
    created_at: float
    started_at: float | None
    completed_at: float | None


@router.post("/enqueue", response_model=JobResponse)
async def enqueue_task(
    req: EnqueueRequest,
    user: User = Depends(get_current_user),
):
    job = await task_queue.enqueue(
        task_type=req.task_type,
        payload=req.payload,
        created_by=user.id,
        max_retries=req.max_retries,
    )
    return JobResponse(**{k: v for k, v in job.to_dict().items() if k in JobResponse.model_fields})


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    status: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
):
    jobs = await task_queue.list_jobs(status=status, limit=limit)
    return [
        JobResponse(**{k: v for k, v in j.to_dict().items() if k in JobResponse.model_fields})
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
):
    job = await task_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(**{k: v for k, v in job.to_dict().items() if k in JobResponse.model_fields})


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    user: User = Depends(get_current_user),
):
    cancelled = await task_queue.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")
    return {"cancelled": True}


@router.get("/stream")
async def stream_job_events(user: User = Depends(get_current_user)):
    """SSE stream of all task queue events (job starts, progress, completions)."""
    import redis.asyncio as aioredis

    async def event_generator():
        pubsub = task_queue.redis.pubsub()
        await pubsub.subscribe(task_queue.CHANNEL)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield {"event": "task_event", "data": message["data"]}
        finally:
            await pubsub.unsubscribe(task_queue.CHANNEL)

    return EventSourceResponse(event_generator())

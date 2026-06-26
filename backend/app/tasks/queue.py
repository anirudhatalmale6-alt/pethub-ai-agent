from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Awaitable

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    task_type: str
    payload: dict[str, Any]
    status: str = JobStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: int = 0
    progress_message: str = ""
    attempt: int = 0
    max_retries: int = 3
    created_by: str = ""
    created_at: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaskQueue:
    QUEUE_KEY = "pethub:jobs:queue"
    JOB_PREFIX = "pethub:job:"
    ACTIVE_KEY = "pethub:jobs:active"
    CHANNEL = "pethub:jobs:events"

    def __init__(self):
        settings = get_settings()
        self._redis: aioredis.Redis | None = None
        self._redis_url = settings.redis_url
        self._handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._running = False

    async def connect(self) -> None:
        if not self._redis:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None

    @property
    def redis(self) -> aioredis.Redis:
        if not self._redis:
            raise RuntimeError("TaskQueue not connected. Call connect() first.")
        return self._redis

    def register_handler(self, task_type: str, handler: Callable[..., Awaitable[Any]]) -> None:
        self._handlers[task_type] = handler
        logger.info(f"Registered task handler: {task_type}")

    async def enqueue(self, task_type: str, payload: dict[str, Any],
                      created_by: str = "", max_retries: int = 3) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            task_type=task_type,
            payload=payload,
            created_by=created_by,
            max_retries=max_retries,
            created_at=time.time(),
        )

        await self.redis.set(f"{self.JOB_PREFIX}{job.id}", json.dumps(job.to_dict()))
        await self.redis.lpush(self.QUEUE_KEY, job.id)
        await self._publish_event(job, "enqueued")

        logger.info(f"Enqueued job {job.id} ({task_type})")
        return job

    async def get_job(self, job_id: str) -> Job | None:
        data = await self.redis.get(f"{self.JOB_PREFIX}{job_id}")
        if not data:
            return None
        return Job.from_dict(json.loads(data))

    async def update_progress(self, job_id: str, progress: int, message: str = "") -> None:
        job = await self.get_job(job_id)
        if not job:
            return
        job.progress = min(100, max(0, progress))
        job.progress_message = message
        await self.redis.set(f"{self.JOB_PREFIX}{job_id}", json.dumps(job.to_dict()))
        await self._publish_event(job, "progress")

    async def cancel_job(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = time.time()
        await self.redis.set(f"{self.JOB_PREFIX}{job_id}", json.dumps(job.to_dict()))
        await self._publish_event(job, "cancelled")
        return True

    async def list_jobs(self, status: str | None = None, limit: int = 50) -> list[Job]:
        keys = []
        async for key in self.redis.scan_iter(f"{self.JOB_PREFIX}*"):
            keys.append(key)
            if len(keys) >= 200:
                break

        jobs = []
        for key in keys:
            data = await self.redis.get(key)
            if data:
                job = Job.from_dict(json.loads(data))
                if status is None or job.status == status:
                    jobs.append(job)

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def _publish_event(self, job: Job, event_type: str) -> None:
        event = {"type": event_type, "job": job.to_dict()}
        await self.redis.publish(self.CHANNEL, json.dumps(event))

    async def _process_job(self, job: Job) -> None:
        handler = self._handlers.get(job.task_type)
        if not handler:
            job.status = JobStatus.FAILED
            job.error = f"No handler for task type: {job.task_type}"
            job.completed_at = time.time()
            await self.redis.set(f"{self.JOB_PREFIX}{job.id}", json.dumps(job.to_dict()))
            await self._publish_event(job, "failed")
            return

        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        job.attempt += 1
        await self.redis.set(f"{self.JOB_PREFIX}{job.id}", json.dumps(job.to_dict()))
        await self.redis.sadd(self.ACTIVE_KEY, job.id)
        await self._publish_event(job, "started")

        try:
            result = await handler(job.id, job.payload, self)
            job.status = JobStatus.COMPLETED
            job.result = result if isinstance(result, dict) else {"output": str(result)}
            job.progress = 100
            job.completed_at = time.time()
            await self._publish_event(job, "completed")
        except Exception as e:
            logger.exception(f"Job {job.id} failed (attempt {job.attempt}/{job.max_retries})")
            if job.attempt < job.max_retries:
                job.status = JobStatus.RETRYING
                job.error = str(e)
                await self.redis.set(f"{self.JOB_PREFIX}{job.id}", json.dumps(job.to_dict()))
                await self._publish_event(job, "retrying")
                await asyncio.sleep(2 ** job.attempt)
                await self.redis.lpush(self.QUEUE_KEY, job.id)
            else:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = time.time()
                await self._publish_event(job, "failed")

        await self.redis.set(f"{self.JOB_PREFIX}{job.id}", json.dumps(job.to_dict()))
        await self.redis.srem(self.ACTIVE_KEY, job.id)

    async def worker_loop(self) -> None:
        self._running = True
        logger.info("Task queue worker started")

        while self._running:
            try:
                result = await self.redis.brpop(self.QUEUE_KEY, timeout=5)
                if result is None:
                    continue

                _, job_id = result
                job = await self.get_job(job_id)
                if not job or job.status == JobStatus.CANCELLED:
                    continue

                await self._process_job(job)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(1)

        logger.info("Task queue worker stopped")

    def stop(self) -> None:
        self._running = False


task_queue = TaskQueue()

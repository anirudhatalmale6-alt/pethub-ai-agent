import asyncio
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import auth, chat
from app.routes import tasks as tasks_router
from app.routes import approvals as approvals_router
from app.tasks.queue import task_queue
from app.tasks.handlers import register_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await task_queue.connect()
    register_handlers()
    worker_task = asyncio.create_task(task_queue.worker_loop())
    yield
    # Shutdown
    task_queue.stop()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await task_queue.disconnect()


app = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url="/api/redoc", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(tasks_router.router)
app.include_router(approvals_router.router)

# Register tools on startup
import app.tools.wordpress  # noqa: F401
import app.tools.vision  # noqa: F401
import app.tools.codegen  # noqa: F401
import app.tools.seo  # noqa: F401
import app.tools.background  # noqa: F401


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@app.get("/api/tools")
async def list_tools():
    from app.tools.registry import registry
    tools = registry.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "requires_approval": t.requires_approval,
            "tags": t.tags,
        }
        for t in tools
    ]

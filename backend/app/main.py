import asyncio
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import auth, chat
from app.routes import tasks as tasks_router
from app.routes import approvals as approvals_router
from app.routes import files as files_router
from app.routes import knowledge as knowledge_router
from app.routes import monitoring as monitoring_router
from app.tasks.queue import task_queue
from app.tasks.handlers import register_handlers
from app.middleware.rate_limit import RateLimitMiddleware

# Register tools
from app.tools import wordpress as _wp  # noqa: F401
from app.tools import vision as _vis  # noqa: F401
from app.tools import codegen as _cg  # noqa: F401
from app.tools import seo as _seo  # noqa: F401
from app.tools import background as _bg  # noqa: F401
from app.tools import wp_seo as _wpseo  # noqa: F401
from app.tools import knowledge as _know  # noqa: F401
from app.tools import mailerlite as _ml  # noqa: F401
from app.tools import amazon as _amz  # noqa: F401
from app.tools import feedback as _fb  # noqa: F401
from app.tools import connector as _conn  # noqa: F401
from app.tools import project as _proj  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    await task_queue.connect()
    register_handlers()
    worker_task = asyncio.create_task(task_queue.worker_loop())
    yield
    task_queue.stop()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await task_queue.disconnect()


application = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url="/api/redoc", lifespan=lifespan)

application.add_middleware(RateLimitMiddleware, requests_per_minute=120)
application.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

application.include_router(auth.router)
application.include_router(chat.router)
application.include_router(tasks_router.router)
application.include_router(approvals_router.router)
application.include_router(files_router.router)
application.include_router(knowledge_router.router)
application.include_router(monitoring_router.router)


@application.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@application.get("/api/tools")
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

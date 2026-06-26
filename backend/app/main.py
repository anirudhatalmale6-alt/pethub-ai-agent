import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import auth, chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

settings = get_settings()

app = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url="/api/redoc")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)

# Register tools on startup
import app.tools.wordpress  # noqa: F401
import app.tools.vision  # noqa: F401
import app.tools.codegen  # noqa: F401
import app.tools.seo  # noqa: F401


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

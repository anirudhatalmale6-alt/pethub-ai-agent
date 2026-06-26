# PetHub AI Agent

AI-powered operations assistant with real-time chat interface, tool-calling architecture, and WordPress integration.

## Architecture

```
Frontend (Next.js + Tailwind CSS)
  |
  | SSE streaming
  v
Backend (FastAPI + Python)
  |
  | Tool-calling agent loop
  v
Agent Engine (OpenAI GPT-4o)
  |
  | Modular tool registry
  v
Tools: WordPress API, Code Gen, Vision, SEO (extensible)
  |
  v
PostgreSQL + Redis
```

## Quick Start

### 1. Clone and configure

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — set your OPENAI_API_KEY and JWT_SECRET
```

### 2. Run with Docker

```bash
# Development
docker compose up -d

# Staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Production
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
```

### 3. Access

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API docs**: http://localhost:8000/api/docs

## Project Structure

```
pethub-ai-agent/
├── backend/
│   ├── app/
│   │   ├── agents/          # Agent engine (LLM loop + orchestration)
│   │   ├── models/          # SQLAlchemy database models
│   │   ├── routes/          # FastAPI endpoints (auth, chat)
│   │   ├── tools/           # Tool registry + tool implementations
│   │   │   ├── registry.py  # Core tool registry
│   │   │   └── wordpress.py # WordPress REST API tools
│   │   ├── utils/           # Auth, helpers
│   │   ├── config.py        # Settings from environment
│   │   ├── database.py      # Database connection
│   │   └── main.py          # FastAPI app
│   ├── migrations/          # Alembic database migrations
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js app router
│   │   ├── components/      # React components
│   │   └── lib/             # API client
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml              # Base config
├── docker-compose.staging.yml      # Staging overrides
└── docker-compose.production.yml   # Production overrides
```

## Adding New Tools

Tools are modular. To add a new integration:

1. Create a file in `backend/app/tools/` (e.g., `shopify.py`)
2. Use the `@registry.tool()` decorator:

```python
from app.tools.registry import registry

@registry.tool(
    name="my_tool",
    description="What this tool does",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"],
    },
    category="my_category",
    requires_approval=False,
)
async def my_tool(param1: str) -> dict:
    # Your implementation
    return {"result": "done"}
```

3. Import it in `backend/app/main.py`:
```python
import app.tools.my_tool  # noqa
```

The agent will automatically discover and use the new tool.

## Security

- JWT authentication for all API routes
- Approval workflow for sensitive operations (bulk edits, plugin installs, etc.)
- Full audit log of all actions
- RBAC support (admin/user roles)
- CORS configured per environment
- No secrets in source code — everything via environment variables

## API Keys You Need

| Service | Get it at | Used for |
|---------|-----------|----------|
| OpenAI | platform.openai.com | GPT-4o agent intelligence |

All keys are set via environment variables in `backend/.env`. You own all keys.

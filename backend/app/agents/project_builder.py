import json
import logging
import os
import zipfile
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.database import async_session

logger = logging.getLogger(__name__)

PROJECTS_DIR = os.environ.get("PROJECTS_DIR", "/app/projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

ANALYSE_PROMPT = """You are a senior software architect. Analyse the user's project request and create a comprehensive specification.

Project request: {request}

Return JSON:
{{
    "project_name": "slug-format name",
    "description": "2-3 sentence project description",
    "tech_stack": {{
        "frontend": "framework choice with reasoning",
        "backend": "framework choice with reasoning",
        "database": "database choice with reasoning",
        "deployment": "deployment approach"
    }},
    "features": [
        {{"name": "feature name", "description": "what it does", "priority": "core|important|nice_to_have"}}
    ],
    "suggested_extras": [
        {{"name": "feature name", "description": "why the user should consider this", "effort": "low|medium|high"}}
    ],
    "pages": [
        {{"name": "page name", "route": "/route", "description": "what this page shows"}}
    ],
    "database_models": [
        {{"name": "ModelName", "fields": [{{"name": "field", "type": "string|int|bool|datetime|json|fk:Model", "description": ""}}], "description": ""}}
    ],
    "api_endpoints": [
        {{"method": "GET|POST|PUT|DELETE", "path": "/api/...", "description": "", "auth_required": true}}
    ]
}}

Be thorough. Include 8-15 features, 5-10 pages, proper database models with relationships, and comprehensive API endpoints. Think about what the user needs even if they didn't explicitly ask."""

GENERATE_FILE_PROMPT = """You are an expert developer. Generate a complete, production-quality file for this project.

Project: {project_name}
Description: {description}
Tech stack: {tech_stack}
File to generate: {filepath}
Purpose: {purpose}
Context: {context}

Generate ONLY the file content. No explanations, no markdown fences. Write real, working, production-quality code with proper error handling, clean structure, and sensible defaults. Include comments only where logic is non-obvious."""


class ProjectBuilder:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def analyse_project(self, request: str) -> dict:
        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": ANALYSE_PROMPT.format(request=request)},
                {"role": "user", "content": "Create the full specification."},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return json.loads(response.choices[0].message.content or "{}")

    async def generate_file(self, project_name: str, description: str,
                            tech_stack: dict, filepath: str, purpose: str,
                            context: str = "") -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": GENERATE_FILE_PROMPT.format(
                    project_name=project_name,
                    description=description,
                    tech_stack=json.dumps(tech_stack),
                    filepath=filepath,
                    purpose=purpose,
                    context=context or "No additional context",
                )},
                {"role": "user", "content": f"Generate {filepath}"},
            ],
            temperature=0.3,
        )
        code = response.choices[0].message.content or ""
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)
        return code

    async def build_project(self, spec: dict, progress_callback=None) -> dict:
        project_name = spec.get("project_name", "project")
        description = spec.get("description", "")
        tech_stack = spec.get("tech_stack", {})
        features = spec.get("features", [])
        pages = spec.get("pages", [])
        models = spec.get("database_models", [])
        endpoints = spec.get("api_endpoints", [])

        project_dir = os.path.join(PROJECTS_DIR, project_name)
        os.makedirs(project_dir, exist_ok=True)

        files_to_generate = self._plan_files(spec)
        total = len(files_to_generate)
        generated = []

        models_context = json.dumps(models)
        endpoints_context = json.dumps(endpoints)
        features_context = json.dumps([f["name"] for f in features])
        pages_context = json.dumps(pages)

        for i, (filepath, purpose) in enumerate(files_to_generate):
            if progress_callback:
                await progress_callback(int((i / total) * 100), f"Generating {filepath}")

            context = f"Models: {models_context[:1000]}\nEndpoints: {endpoints_context[:1000]}\nFeatures: {features_context}\nPages: {pages_context[:500]}"

            code = await self.generate_file(project_name, description, tech_stack, filepath, purpose, context)

            full_path = os.path.join(project_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(code)

            generated.append(filepath)

        zip_path = os.path.join(PROJECTS_DIR, f"{project_name}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filepath in generated:
                full_path = os.path.join(project_dir, filepath)
                zf.write(full_path, os.path.join(project_name, filepath))

        return {
            "project_name": project_name,
            "project_dir": project_dir,
            "zip_path": zip_path,
            "files_generated": generated,
            "file_count": len(generated),
            "zip_size_kb": round(os.path.getsize(zip_path) / 1024, 1),
        }

    def _plan_files(self, spec: dict) -> list[tuple[str, str]]:
        tech = spec.get("tech_stack", {})
        frontend = tech.get("frontend", "").lower()
        backend = tech.get("backend", "").lower()
        models = spec.get("database_models", [])
        pages = spec.get("pages", [])
        endpoints = spec.get("api_endpoints", [])

        files = []

        files.append(("README.md", "Project documentation with setup instructions, architecture overview, and feature list"))
        files.append(("docker-compose.yml", "Docker Compose config for all services"))
        files.append((".gitignore", "Git ignore for Node, Python, Docker, env files"))

        if "next" in frontend or "react" in frontend:
            files.append(("frontend/package.json", "Node.js dependencies for Next.js frontend"))
            files.append(("frontend/tsconfig.json", "TypeScript configuration"))
            files.append(("frontend/next.config.js", "Next.js configuration"))
            files.append(("frontend/tailwind.config.ts", "Tailwind CSS configuration with custom theme"))
            files.append(("frontend/postcss.config.js", "PostCSS configuration for Tailwind"))
            files.append(("frontend/src/app/globals.css", "Global CSS with Tailwind directives and custom styles"))
            files.append(("frontend/src/app/layout.tsx", "Root layout with metadata and font setup"))
            files.append(("frontend/src/app/page.tsx", "Homepage component"))
            files.append(("frontend/src/lib/api.ts", "API client with auth helpers"))
            files.append(("frontend/Dockerfile", "Multi-stage Dockerfile for Next.js"))

            for page in pages:
                route = page.get("route", "").strip("/")
                if route and route != "":
                    files.append((f"frontend/src/app/{route}/page.tsx", f"Page: {page.get('name', '')} - {page.get('description', '')}"))

        if "fastapi" in backend or "python" in backend:
            files.append(("backend/requirements.txt", "Python dependencies"))
            files.append(("backend/app/__init__.py", "Package init"))
            files.append(("backend/app/main.py", "FastAPI application with all routes, CORS, and lifespan"))
            files.append(("backend/app/config.py", "Settings from environment variables"))
            files.append(("backend/app/database.py", "SQLAlchemy async engine and session setup"))
            files.append(("backend/app/models.py", f"SQLAlchemy models: {', '.join(m['name'] for m in models)}"))
            files.append(("backend/app/routes.py", f"API routes for {len(endpoints)} endpoints"))
            files.append(("backend/app/auth.py", "JWT authentication with login/register"))
            files.append(("backend/Dockerfile", "Python Dockerfile"))

        files.append(("backend/alembic.ini", "Alembic migration config"))
        files.append(("backend/migrations/env.py", "Alembic environment setup"))
        files.append(("backend/migrations/versions/001_initial.py", "Initial database migration"))
        files.append(("backend/.env.example", "Environment variables template"))

        return files


project_builder = ProjectBuilder()

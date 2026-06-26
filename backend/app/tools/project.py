import json
import logging
import os

from app.tools.registry import registry
from app.agents.project_builder import project_builder, PROJECTS_DIR

logger = logging.getLogger(__name__)


@registry.tool(
    name="design_project",
    description="Analyse a project idea and create a full specification with architecture, features, database models, API endpoints, and suggested extras. Use this first before build_project.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What you want to build. Be as detailed as possible - the more context, the better the design."},
        },
        "required": ["description"],
    },
    category="project",
)
async def design_project(description: str = "") -> dict:
    spec = await project_builder.analyse_project(description)

    spec_path = os.path.join(PROJECTS_DIR, f"{spec.get('project_name', 'project')}_spec.json")
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)

    core_features = [f for f in spec.get("features", []) if f.get("priority") == "core"]
    important_features = [f for f in spec.get("features", []) if f.get("priority") == "important"]
    nice_features = [f for f in spec.get("features", []) if f.get("priority") == "nice_to_have"]

    return {
        "project_name": spec.get("project_name", ""),
        "description": spec.get("description", ""),
        "tech_stack": spec.get("tech_stack", {}),
        "features": {
            "core": [f["name"] for f in core_features],
            "important": [f["name"] for f in important_features],
            "nice_to_have": [f["name"] for f in nice_features],
        },
        "suggested_extras": spec.get("suggested_extras", []),
        "pages": len(spec.get("pages", [])),
        "database_models": len(spec.get("database_models", [])),
        "api_endpoints": len(spec.get("api_endpoints", [])),
        "spec_saved_to": spec_path,
        "next_step": "Review the design. If it looks good, use build_project with the project name to generate all the code.",
    }


@registry.tool(
    name="build_project",
    description="Generate a complete, feature-rich codebase from a project specification. Run design_project first to create the spec. This generates all frontend, backend, database, and deployment files.",
    parameters={
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "description": "Project name from design_project output"},
        },
        "required": ["project_name"],
    },
    category="project",
    requires_approval=True,
)
async def build_project(project_name: str = "") -> dict:
    spec_path = os.path.join(PROJECTS_DIR, f"{project_name}_spec.json")
    if not os.path.exists(spec_path):
        return {"error": f"No spec found for '{project_name}'. Run design_project first."}

    with open(spec_path) as f:
        spec = json.load(f)

    result = await project_builder.build_project(spec)

    return {
        "project_name": result["project_name"],
        "files_generated": result["file_count"],
        "file_list": result["files_generated"],
        "zip_path": result["zip_path"],
        "zip_size_kb": result["zip_size_kb"],
        "project_dir": result["project_dir"],
        "message": f"Project '{project_name}' generated with {result['file_count']} files. Zip ready at {result['zip_path']}.",
        "next_steps": [
            "Review the generated code",
            "Push to a GitHub repository",
            "Deploy with Docker: docker compose up -d",
        ],
    }


@registry.tool(
    name="list_projects",
    description="List all generated projects.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="project",
)
async def list_projects() -> dict:
    projects = []
    specs = []

    if os.path.exists(PROJECTS_DIR):
        for item in os.listdir(PROJECTS_DIR):
            full = os.path.join(PROJECTS_DIR, item)
            if os.path.isdir(full) and item != "__pycache__":
                files = sum(1 for _, _, fs in os.walk(full) for _ in fs)
                projects.append({"name": item, "files": files})
            elif item.endswith("_spec.json"):
                specs.append(item.replace("_spec.json", ""))
            elif item.endswith(".zip"):
                size = round(os.path.getsize(full) / 1024, 1)
                projects.append({"name": item, "type": "zip", "size_kb": size})

    return {
        "projects": projects,
        "specs_available": specs,
    }

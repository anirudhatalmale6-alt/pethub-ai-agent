import importlib
import importlib.util
import json
import logging
import os
import re
import sys
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

CONNECTORS_DIR = os.environ.get("CONNECTORS_DIR", "/app/connectors")
os.makedirs(CONNECTORS_DIR, exist_ok=True)

GENERATE_PROMPT = """You are an expert Python developer specialising in API integrations. Generate a tool connector file for the PetHub AI Agent system.

The user wants to connect to: {service_name}
Additional details: {details}

Generate a complete Python file that:
1. Imports from app.tools.registry import registry
2. Uses the @registry.tool() decorator to register one or more tools
3. Uses httpx for HTTP requests (async)
4. Handles errors gracefully
5. Returns clean dict results
6. Has sensible defaults for optional parameters
7. Uses API keys from environment variables (os.environ.get)

Template to follow:
```python
import os
import logging
import httpx
from app.tools.registry import registry

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("SERVICE_API_KEY", "")

@registry.tool(
    name="service_action",
    description="What this tool does",
    parameters={{
        "type": "object",
        "properties": {{
            "param1": {{"type": "string", "description": "..."}},
        }},
        "required": ["param1"],
    }},
    category="custom",
)
async def service_action(param1: str = "") -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get("https://api.example.com/endpoint", headers={{"Authorization": f"Bearer {{API_KEY}}"}}, params={{"q": param1}})
        resp.raise_for_status()
        data = resp.json()
    return {{"result": data}}
```

Rules:
- All function parameters MUST have default values (e.g. param: str = "")
- Use requires_approval=True for any action that modifies data
- Category should be "custom"
- Include 2-4 useful tools for the service
- Return ONLY the Python code, no explanations

Generate the complete file now."""

REVIEW_PROMPT = """Review this Python tool connector code for security and quality issues.

Code:
{code}

Check for:
1. SECURITY: Does it execute arbitrary code? Does it access the filesystem unsafely? Does it expose credentials in responses?
2. IMPORTS: Does it only import standard/allowed libraries (httpx, os, logging, json, re)?
3. QUALITY: Are error cases handled? Are responses clean dicts?
4. SAFETY: Could this harm the server or leak data?

Return JSON:
{{
    "safe": true/false,
    "issues": ["list of issues found"],
    "risk_level": "low/medium/high",
    "summary": "one line summary"
}}"""


@registry.tool(
    name="generate_api_connector",
    description="Generate a new API tool connector. Describe the service you want to integrate and the agent will research and generate the integration code for your review. After approval, the tool becomes available immediately.",
    parameters={
        "type": "object",
        "properties": {
            "service_name": {"type": "string", "description": "Name of the API/service to connect to (e.g. 'Ahrefs', 'Google PageSpeed', 'Unsplash')"},
            "details": {"type": "string", "description": "What you want the integration to do, any specific endpoints or features", "default": ""},
            "api_key_env_name": {"type": "string", "description": "Environment variable name for the API key (e.g. AHREFS_API_KEY)", "default": ""},
        },
        "required": ["service_name"],
    },
    category="system",
    requires_approval=True,
)
async def generate_api_connector(service_name: str = "", details: str = "",
                                  api_key_env_name: str = "") -> dict:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    if api_key_env_name:
        details += f"\nAPI key is stored in environment variable: {api_key_env_name}"

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": GENERATE_PROMPT.format(
                service_name=service_name, details=details or "Create useful tools for this service"
            )},
            {"role": "user", "content": f"Generate the connector for {service_name}"},
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

    review_resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": REVIEW_PROMPT.format(code=code)},
            {"role": "user", "content": "Review this code."},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    review = json.loads(review_resp.choices[0].message.content or "{}")

    slug = re.sub(r'[^a-z0-9]', '_', service_name.lower()).strip('_')
    filename = f"connector_{slug}.py"
    filepath = os.path.join(CONNECTORS_DIR, filename)

    with open(filepath, "w") as f:
        f.write(code)

    return {
        "service": service_name,
        "filename": filename,
        "filepath": filepath,
        "code_preview": code[:2000],
        "code_length": len(code),
        "security_review": review,
        "status": "generated_pending_install",
        "next_step": "If the code looks good and the security review passes, use install_connector to activate it.",
    }


@registry.tool(
    name="install_connector",
    description="Install and activate a previously generated API connector. This loads the connector code and registers its tools immediately.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Connector filename (e.g. connector_ahrefs.py)"},
        },
        "required": ["filename"],
    },
    category="system",
    requires_approval=True,
)
async def install_connector(filename: str = "") -> dict:
    filepath = os.path.join(CONNECTORS_DIR, filename)

    if not os.path.exists(filepath):
        return {"error": f"Connector file not found: {filename}"}

    with open(filepath) as f:
        code = f.read()

    dangerous = ["subprocess", "exec(", "eval(", "os.system", "__import__",
                  "shutil.rmtree", "os.remove", "open(", "compile("]
    found_dangerous = [d for d in dangerous if d in code and d != "open("]
    if "open(" in code:
        open_contexts = re.findall(r'open\([^)]+\)', code)
        for ctx in open_contexts:
            if not any(safe in ctx for safe in ["filepath", "CONNECTORS_DIR", "connector"]):
                found_dangerous.append(f"open(): {ctx[:50]}")

    if found_dangerous:
        return {
            "error": "Connector contains potentially dangerous code",
            "dangerous_patterns": found_dangerous,
            "status": "blocked",
        }

    try:
        module_name = f"connectors.{filename.replace('.py', '')}"
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if not spec or not spec.loader:
            return {"error": "Could not load connector module"}

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        tools_before = len(registry.list_tools())
        tools_after = len(registry.list_tools())
        new_tools = tools_after - tools_before

        new_tool_names = [t.name for t in registry.list_tools()
                         if t.category == "custom"]

        return {
            "status": "installed",
            "filename": filename,
            "new_tools_registered": new_tools,
            "custom_tools": new_tool_names,
            "message": f"Connector installed. {new_tools} new tools available.",
        }

    except Exception as e:
        return {"error": f"Failed to install connector: {str(e)}", "status": "failed"}


@registry.tool(
    name="list_connectors",
    description="List all generated and installed custom API connectors.",
    parameters={
        "type": "object",
        "properties": {},
    },
    category="system",
)
async def list_connectors() -> dict:
    connectors = []
    if os.path.exists(CONNECTORS_DIR):
        for f in os.listdir(CONNECTORS_DIR):
            if f.endswith(".py") and f.startswith("connector_"):
                filepath = os.path.join(CONNECTORS_DIR, f)
                size = os.path.getsize(filepath)
                connectors.append({
                    "filename": f,
                    "size_bytes": size,
                    "service": f.replace("connector_", "").replace(".py", "").replace("_", " ").title(),
                })

    custom_tools = [t.name for t in registry.list_tools() if t.category == "custom"]

    return {
        "connector_files": connectors,
        "active_custom_tools": custom_tools,
        "connectors_dir": CONNECTORS_DIR,
    }

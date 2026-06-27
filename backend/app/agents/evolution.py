import importlib
import importlib.util
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

EVOLUTION_DIR = os.environ.get("EVOLUTION_DIR", "/app/evolution")
SANDBOX_DIR = os.path.join(EVOLUTION_DIR, "sandbox")
ACTIVE_DIR = os.path.join(EVOLUTION_DIR, "active")
ARCHIVE_DIR = os.path.join(EVOLUTION_DIR, "archive")
REGISTRY_FILE = os.path.join(EVOLUTION_DIR, "registry.json")

for d in [EVOLUTION_DIR, SANDBOX_DIR, ACTIVE_DIR, ARCHIVE_DIR]:
    os.makedirs(d, exist_ok=True)

DANGEROUS_PATTERNS = [
    "subprocess", "os.system", "exec(", "eval(", "__import__",
    "shutil.rmtree", "os.remove(", "os.unlink", "compile(",
    "importlib.import_module",
]

PROPOSE_PROMPT = """You are a system architect. The AI agent needs a new tool or workflow.

Request: {request}
Existing tools: {existing_tools}

Generate a complete Python tool module. Follow this exact pattern:
- Import from app.tools.registry import registry
- Use @registry.tool() decorator
- Use httpx for HTTP calls (async)
- All function params must have default values
- Return dict results
- Handle errors gracefully
- Category should be "evolved"

Return ONLY Python code, no explanations."""

TEST_PROMPT = """Review this Python tool code and generate test scenarios.

Code:
{code}

Return JSON:
{{
    "safe": true/false,
    "security_issues": ["list of any security concerns"],
    "test_scenarios": [
        {{"name": "test name", "tool": "tool_name", "arguments": {{...}}, "expected": "what should happen"}}
    ],
    "quality_score": 0-100,
    "recommendation": "activate|revise|reject"
}}"""


class EvolutionRegistry:
    def __init__(self):
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(REGISTRY_FILE):
            try:
                with open(REGISTRY_FILE) as f:
                    self._entries = json.load(f)
            except Exception:
                self._entries = []

    def _save(self):
        with open(REGISTRY_FILE, "w") as f:
            json.dump(self._entries, f, indent=2, default=str)

    def add(self, entry: dict):
        self._entries.append(entry)
        self._save()

    def get(self, module_id: str) -> dict | None:
        return next((e for e in self._entries if e["id"] == module_id), None)

    def update_status(self, module_id: str, status: str, details: dict | None = None):
        for e in self._entries:
            if e["id"] == module_id:
                e["status"] = status
                e["updated_at"] = datetime.now(timezone.utc).isoformat()
                if details:
                    e.update(details)
        self._save()

    def list_all(self, status: str = "") -> list[dict]:
        if status:
            return [e for e in self._entries if e.get("status") == status]
        return list(self._entries)


class EvolutionEngine:
    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self.registry = EvolutionRegistry()

    async def propose(self, request: str) -> dict:
        existing = [f"{t.name}: {t.description[:50]}" for t in registry.list_tools()]

        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": PROPOSE_PROMPT.format(
                    request=request, existing_tools="\n".join(existing)
                )},
                {"role": "user", "content": f"Generate the tool for: {request}"},
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

        module_id = str(uuid.uuid4())[:8]
        version = 1
        filename = f"module_{module_id}_v{version}.py"

        sandbox_path = os.path.join(SANDBOX_DIR, filename)
        with open(sandbox_path, "w") as f:
            f.write(code)

        entry = {
            "id": module_id,
            "request": request,
            "filename": filename,
            "version": version,
            "status": "proposed",
            "sandbox_path": sandbox_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.registry.add(entry)

        return {
            "module_id": module_id,
            "filename": filename,
            "code_preview": code[:2000],
            "code_length": len(code),
            "status": "proposed",
            "next_step": "Use sandbox_test to validate, then activate to go live.",
        }

    async def sandbox_test(self, module_id: str) -> dict:
        entry = self.registry.get(module_id)
        if not entry:
            return {"error": f"Module {module_id} not found"}

        sandbox_path = entry.get("sandbox_path", "")
        if not os.path.exists(sandbox_path):
            return {"error": "Sandbox file not found"}

        with open(sandbox_path) as f:
            code = f.read()

        security_issues = [p for p in DANGEROUS_PATTERNS if p in code]
        if security_issues:
            self.registry.update_status(module_id, "failed_security", {"security_issues": security_issues})
            return {
                "module_id": module_id,
                "status": "failed_security",
                "issues": security_issues,
                "message": "Code contains dangerous patterns. Cannot proceed.",
            }

        try:
            compile(code, sandbox_path, "exec")
            syntax_ok = True
        except SyntaxError as e:
            self.registry.update_status(module_id, "failed_syntax", {"syntax_error": str(e)})
            return {"module_id": module_id, "status": "failed_syntax", "error": str(e)}

        test_response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {"role": "system", "content": TEST_PROMPT.format(code=code[:3000])},
                {"role": "user", "content": "Review and generate tests."},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        test_results = json.loads(test_response.choices[0].message.content or "{}")

        safe = test_results.get("safe", False) and not security_issues
        quality = test_results.get("quality_score", 0)
        recommendation = test_results.get("recommendation", "reject")

        status = "sandbox_passed" if safe and quality >= 60 and recommendation != "reject" else "sandbox_failed"
        self.registry.update_status(module_id, status, {
            "test_results": test_results,
            "quality_score": quality,
        })

        return {
            "module_id": module_id,
            "status": status,
            "safe": safe,
            "quality_score": quality,
            "recommendation": recommendation,
            "security_issues": test_results.get("security_issues", []),
            "test_scenarios": test_results.get("test_scenarios", []),
            "next_step": "Use activate_module to make it live." if status == "sandbox_passed" else "Revise or reject.",
        }

    async def activate(self, module_id: str) -> dict:
        entry = self.registry.get(module_id)
        if not entry:
            return {"error": f"Module {module_id} not found"}

        if entry.get("status") != "sandbox_passed":
            return {"error": f"Module must pass sandbox testing first. Current status: {entry.get('status')}"}

        sandbox_path = entry.get("sandbox_path", "")
        if not os.path.exists(sandbox_path):
            return {"error": "Sandbox file not found"}

        active_path = os.path.join(ACTIVE_DIR, entry["filename"])

        with open(sandbox_path) as f:
            code = f.read()
        with open(active_path, "w") as f:
            f.write(code)

        tools_before = set(t.name for t in registry.list_tools())

        try:
            module_name = f"evolution.{entry['filename'].replace('.py', '')}"
            spec = importlib.util.spec_from_file_location(module_name, active_path)
            if not spec or not spec.loader:
                return {"error": "Could not load module"}

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            tools_after = set(t.name for t in registry.list_tools())
            new_tools = list(tools_after - tools_before)

            self.registry.update_status(module_id, "active", {
                "active_path": active_path,
                "new_tools": new_tools,
            })

            return {
                "module_id": module_id,
                "status": "active",
                "new_tools": new_tools,
                "message": f"Module activated. {len(new_tools)} new tools available.",
            }

        except Exception as e:
            self.registry.update_status(module_id, "activation_failed", {"error": str(e)})
            if os.path.exists(active_path):
                os.remove(active_path)
            return {"module_id": module_id, "status": "activation_failed", "error": str(e)}

    async def rollback(self, module_id: str) -> dict:
        entry = self.registry.get(module_id)
        if not entry:
            return {"error": f"Module {module_id} not found"}

        active_path = entry.get("active_path", "")
        if active_path and os.path.exists(active_path):
            archive_path = os.path.join(ARCHIVE_DIR, f"rolled_back_{entry['filename']}")
            os.rename(active_path, archive_path)

        module_name = f"evolution.{entry['filename'].replace('.py', '')}"
        if module_name in sys.modules:
            del sys.modules[module_name]

        for tool_name in entry.get("new_tools", []):
            if registry.get(tool_name):
                registry._tools.pop(tool_name, None)

        self.registry.update_status(module_id, "rolled_back")

        return {
            "module_id": module_id,
            "status": "rolled_back",
            "removed_tools": entry.get("new_tools", []),
            "message": "Module rolled back. Tools removed.",
        }


evolution_engine = EvolutionEngine()

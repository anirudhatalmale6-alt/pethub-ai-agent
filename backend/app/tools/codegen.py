import logging
import os
import zipfile
import tempfile
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.registry import registry

logger = logging.getLogger(__name__)

PLUGINS_DIR = os.environ.get("PLUGINS_DIR", "/app/plugins")
os.makedirs(PLUGINS_DIR, exist_ok=True)


async def _generate_code(prompt: str, language: str = "php") -> str:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    system_msg = f"""You are an expert {language} developer. Generate clean, production-ready code.
- Follow best practices and security standards
- Include proper error handling
- Add minimal inline comments only where logic is non-obvious
- For WordPress plugins, follow WordPress coding standards
- Return ONLY the code, no explanations or markdown fences."""

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
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


@registry.tool(
    name="generate_wp_plugin",
    description="Generate a WordPress plugin from a description. Creates the plugin PHP file, readme.txt, and a zip file ready for installation.",
    parameters={
        "type": "object",
        "properties": {
            "plugin_name": {"type": "string", "description": "Plugin name in slug format (e.g. my-custom-plugin)"},
            "description": {"type": "string", "description": "Detailed description of what the plugin should do"},
            "features": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of specific features the plugin should have",
            },
        },
        "required": ["plugin_name", "description"],
    },
    category="codegen",
    requires_approval=True,
)
async def generate_wp_plugin(plugin_name: str, description: str,
                              features: list[str] | None = None) -> dict:
    feature_list = "\n".join(f"- {f}" for f in (features or []))
    prompt = f"""Create a WordPress plugin with the following specification:

Plugin Name: {plugin_name}
Description: {description}
{f'Features:{chr(10)}{feature_list}' if feature_list else ''}

Requirements:
- Include proper plugin header comment
- Use WordPress hooks and filters correctly
- Sanitize and validate all input
- Use nonces for form submissions
- Prefix all functions with a unique prefix based on the plugin name
- Include activation and deactivation hooks if needed
- Follow WordPress coding standards"""

    plugin_code = await _generate_code(prompt, "php")

    readme_prompt = f"""Create a WordPress readme.txt file for this plugin:
Name: {plugin_name}
Description: {description}
{f'Features:{chr(10)}{feature_list}' if feature_list else ''}

Follow the standard WordPress readme.txt format with:
=== Plugin Name ===
Contributors, tags, requires at least, tested up to, stable tag, license
== Description ==
== Installation ==
== Changelog =="""

    readme = await _generate_code(readme_prompt, "text")

    plugin_dir = os.path.join(PLUGINS_DIR, plugin_name)
    os.makedirs(plugin_dir, exist_ok=True)

    plugin_file = os.path.join(plugin_dir, f"{plugin_name}.php")
    with open(plugin_file, "w") as f:
        f.write(plugin_code)

    readme_file = os.path.join(plugin_dir, "readme.txt")
    with open(readme_file, "w") as f:
        f.write(readme)

    zip_path = os.path.join(PLUGINS_DIR, f"{plugin_name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(plugin_file, f"{plugin_name}/{plugin_name}.php")
        zf.write(readme_file, f"{plugin_name}/readme.txt")

    return {
        "plugin_name": plugin_name,
        "files": [f"{plugin_name}/{plugin_name}.php", f"{plugin_name}/readme.txt"],
        "zip_path": zip_path,
        "zip_size_kb": round(os.path.getsize(zip_path) / 1024, 1),
        "message": f"Plugin '{plugin_name}' generated successfully. Ready for deployment.",
    }


@registry.tool(
    name="deploy_plugin_wp_api",
    description="Deploy a generated plugin to WordPress via the REST API (uploads as a zip file).",
    parameters={
        "type": "object",
        "properties": {
            "wp_url": {"type": "string", "description": "WordPress site URL"},
            "wp_user": {"type": "string", "description": "WordPress application password username"},
            "wp_password": {"type": "string", "description": "WordPress application password"},
            "zip_path": {"type": "string", "description": "Local path to the plugin zip file"},
        },
        "required": ["wp_url", "wp_user", "wp_password", "zip_path"],
    },
    category="codegen",
    requires_approval=True,
)
async def deploy_plugin_wp_api(wp_url: str, wp_user: str, wp_password: str,
                                zip_path: str) -> dict:
    if not os.path.exists(zip_path):
        return {"error": f"Zip file not found: {zip_path}"}

    upload_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/plugins"

    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(zip_path, "rb") as f:
            files = {"file": (os.path.basename(zip_path), f, "application/zip")}
            response = await client.post(
                upload_url, auth=(wp_user, wp_password), files=files,
            )

        if response.status_code == 201:
            result = response.json()
            return {
                "status": "installed",
                "plugin": result.get("plugin", ""),
                "name": result.get("name", ""),
                "version": result.get("version", ""),
            }
        else:
            return {
                "status": "failed",
                "error": response.text[:500],
                "status_code": response.status_code,
                "fallback": "Try deploying via SFTP using deploy_plugin_sftp instead.",
            }


@registry.tool(
    name="deploy_plugin_sftp",
    description="Deploy a generated plugin to WordPress via SFTP/SSH. Uploads the plugin directory directly to wp-content/plugins/.",
    parameters={
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Server hostname or IP"},
            "username": {"type": "string", "description": "SSH/SFTP username"},
            "password": {"type": "string", "description": "SSH/SFTP password (or use key_path)"},
            "key_path": {"type": "string", "description": "Path to SSH private key (alternative to password)"},
            "port": {"type": "integer", "description": "SSH port", "default": 22},
            "wp_path": {"type": "string", "description": "WordPress root path on server (e.g. /var/www/html)"},
            "plugin_name": {"type": "string", "description": "Plugin slug name"},
        },
        "required": ["host", "username", "wp_path", "plugin_name"],
    },
    category="codegen",
    requires_approval=True,
)
async def deploy_plugin_sftp(host: str, username: str, wp_path: str, plugin_name: str,
                              password: str = "", key_path: str = "", port: int = 22) -> dict:
    import paramiko

    local_dir = os.path.join(PLUGINS_DIR, plugin_name)
    if not os.path.exists(local_dir):
        return {"error": f"Plugin directory not found: {local_dir}"}

    remote_plugin_dir = f"{wp_path.rstrip('/')}/wp-content/plugins/{plugin_name}"

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {"hostname": host, "port": port, "username": username}
        if key_path and os.path.exists(key_path):
            connect_kwargs["key_filename"] = key_path
        elif password:
            connect_kwargs["password"] = password
        else:
            return {"error": "Either password or key_path is required"}

        ssh.connect(**connect_kwargs)
        sftp = ssh.open_sftp()

        try:
            sftp.mkdir(remote_plugin_dir)
        except IOError:
            pass

        uploaded = []
        for fname in os.listdir(local_dir):
            local_path = os.path.join(local_dir, fname)
            remote_path = f"{remote_plugin_dir}/{fname}"
            sftp.put(local_path, remote_path)
            uploaded.append(fname)

        sftp.close()
        ssh.close()

        return {
            "status": "deployed",
            "host": host,
            "remote_path": remote_plugin_dir,
            "files_uploaded": uploaded,
            "message": f"Plugin deployed to {remote_plugin_dir}. Activate it from the WordPress admin.",
        }

    except Exception as e:
        return {"status": "failed", "error": str(e)}


@registry.tool(
    name="generate_code",
    description="Generate code in any language from a description. Returns the generated code as text.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What the code should do"},
            "language": {"type": "string", "description": "Programming language (php, javascript, python, css, html, etc.)", "default": "php"},
            "filename": {"type": "string", "description": "Optional filename to save the code to"},
        },
        "required": ["description"],
    },
    category="codegen",
)
async def generate_code(description: str, language: str = "php", filename: str = "") -> dict:
    code = await _generate_code(description, language)

    result: dict[str, Any] = {
        "language": language,
        "code": code[:3000],
        "length": len(code),
    }

    if filename:
        filepath = os.path.join(PLUGINS_DIR, filename)
        with open(filepath, "w") as f:
            f.write(code)
        result["saved_to"] = filepath

    return result

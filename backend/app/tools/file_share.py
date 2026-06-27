import logging
import os

from app.tools.registry import registry

logger = logging.getLogger(__name__)

SEARCHABLE_DIRS = ["/app/projects", "/app/plugins", "/app/connectors",
                   "/app/evolution/active", "/app/screenshots", "/app/uploads"]


@registry.tool(
    name="share_file",
    description="Generate a download link for a file so the user can download it directly from the chat. Use after generating plugins, projects, or any files.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Filename or path to share (e.g. 'my-project.zip' or '/app/projects/my-project.zip')"},
        },
        "required": ["filename"],
    },
    category="system",
)
async def share_file(filename: str = "") -> dict:
    filepath = None

    if os.path.exists(filename) and os.path.isfile(filename):
        filepath = filename
    else:
        for base_dir in SEARCHABLE_DIRS:
            for root, dirs, files in os.walk(base_dir):
                for f in files:
                    if f == filename or f == os.path.basename(filename):
                        filepath = os.path.join(root, f)
                        break
                if filepath:
                    break
            if filepath:
                break

    if not filepath:
        return {"error": f"File '{filename}' not found"}

    basename = os.path.basename(filepath)
    size_kb = round(os.path.getsize(filepath) / 1024, 1)

    return {
        "filename": basename,
        "size_kb": size_kb,
        "download_url": f"/api/download/{basename}",
        "download_link": f"[Download {basename} ({size_kb} KB)](/api/download/{basename})",
        "message": f"File ready for download: {basename} ({size_kb} KB)",
    }

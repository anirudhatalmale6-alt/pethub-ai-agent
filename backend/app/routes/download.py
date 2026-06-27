import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.models.models import User
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/download", tags=["download"])

ALLOWED_DIRS = ["/app/projects", "/app/plugins", "/app/connectors",
                "/app/evolution", "/app/screenshots", "/app/uploads", "/app/sitemaps"]


@router.get("/{filename:path}")
async def download_file(
    filename: str,
    user: User = Depends(get_current_user),
):
    filepath = None
    for base_dir in ALLOWED_DIRS:
        candidate = os.path.join(base_dir, filename)
        if os.path.exists(candidate) and os.path.isfile(candidate):
            real = os.path.realpath(candidate)
            if any(real.startswith(os.path.realpath(d)) for d in ALLOWED_DIRS):
                filepath = real
                break

    if not filepath:
        for base_dir in ALLOWED_DIRS:
            for root, dirs, files in os.walk(base_dir):
                for f in files:
                    if f == filename:
                        filepath = os.path.join(root, f)
                        break
                if filepath:
                    break
            if filepath:
                break

    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    basename = os.path.basename(filepath)
    if filepath.endswith(".zip"):
        media_type = "application/zip"
    elif filepath.endswith(".py"):
        media_type = "text/x-python"
    elif filepath.endswith(".json"):
        media_type = "application/json"
    elif filepath.endswith(".png"):
        media_type = "image/png"
    elif filepath.endswith(".jpg") or filepath.endswith(".jpeg"):
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"

    return FileResponse(filepath, filename=basename, media_type=media_type)

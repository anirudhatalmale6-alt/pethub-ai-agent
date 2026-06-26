import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import User
from app.models.files import StoredFile
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/files", tags=["files"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    description: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "file")[1]
    stored_name = f"{file_id}{ext}"
    storage_path = os.path.join(UPLOAD_DIR, stored_name)

    content = await file.read()
    with open(storage_path, "wb") as f:
        f.write(content)

    stored = StoredFile(
        id=file_id,
        filename=stored_name,
        original_name=file.filename or "file",
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        storage_path=storage_path,
        storage_backend="local",
        uploaded_by=user.id,
        description=description,
    )
    db.add(stored)
    await db.commit()

    return {
        "id": file_id,
        "filename": file.filename,
        "size_kb": round(len(content) / 1024, 1),
        "content_type": file.content_type,
        "url": f"/api/files/{file_id}",
    }


@router.get("/")
async def list_files(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StoredFile).order_by(StoredFile.created_at.desc()).limit(limit)
    )
    files = result.scalars().all()
    return [
        {
            "id": f.id,
            "filename": f.original_name,
            "size_kb": round(f.size_bytes / 1024, 1),
            "content_type": f.content_type,
            "description": f.description,
            "created_at": f.created_at.isoformat(),
            "url": f"/api/files/{f.id}",
        }
        for f in files
    ]


@router.get("/{file_id}")
async def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored = result.scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=404, detail="File not found")

    if not os.path.exists(stored.storage_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(stored.storage_path, filename=stored.original_name, media_type=stored.content_type)


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(StoredFile).where(StoredFile.id == file_id))
    stored = result.scalar_one_or_none()
    if not stored:
        raise HTTPException(status_code=404, detail="File not found")

    if os.path.exists(stored.storage_path):
        os.remove(stored.storage_path)

    await db.delete(stored)
    await db.commit()
    return {"deleted": True, "filename": stored.original_name}

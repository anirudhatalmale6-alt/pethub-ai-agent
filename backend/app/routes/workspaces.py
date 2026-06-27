from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.models.models import User
from app.utils.auth import get_current_user
from app.agents.workspace import workspace_manager

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str
    domain: str
    wp_url: str = ""
    wp_user: str = ""
    wp_password: str = ""
    description: str = ""
    affiliate_tag: str = ""


class SwitchRequest(BaseModel):
    workspace: str


@router.get("/")
async def list_ws(user: User = Depends(get_current_user)):
    workspaces = workspace_manager.list_all()
    active = workspace_manager.active
    return {
        "workspaces": workspaces,
        "active": {"id": active.id, "name": active.name, "domain": active.domain} if active else None,
    }


@router.post("/")
async def create_ws(req: CreateWorkspaceRequest, user: User = Depends(get_current_user)):
    try:
        ws = workspace_manager.create(
            req.name, req.domain, req.wp_url, req.wp_user,
            req.wp_password, req.description, req.affiliate_tag,
        )
        return {"status": "created", "id": ws.id, "name": ws.name, "domain": ws.domain}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/switch")
async def switch_ws(req: SwitchRequest, user: User = Depends(get_current_user)):
    ws = workspace_manager.switch(req.workspace)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"status": "switched", "id": ws.id, "name": ws.name, "domain": ws.domain}


@router.delete("/{workspace_id}")
async def delete_ws(workspace_id: str, user: User = Depends(get_current_user)):
    removed = workspace_manager.remove(workspace_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"deleted": True}

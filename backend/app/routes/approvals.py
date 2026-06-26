from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import User, ToolExecution, AuditLog
from app.utils.auth import get_current_user
from app.tools.registry import registry

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalAction(BaseModel):
    approved: bool


class PendingApproval(BaseModel):
    id: str
    tool_name: str
    arguments: dict
    conversation_id: str
    created_at: str

    class Config:
        from_attributes = True


class BatchApprovalRequest(BaseModel):
    execution_ids: list[str]
    approved: bool


@router.get("/pending", response_model=list[PendingApproval])
async def list_pending_approvals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ToolExecution)
        .where(ToolExecution.status == "awaiting_approval")
        .order_by(ToolExecution.created_at.desc())
    )
    executions = result.scalars().all()
    return [
        PendingApproval(
            id=e.id,
            tool_name=e.tool_name,
            arguments=e.arguments,
            conversation_id=e.conversation_id,
            created_at=e.created_at.isoformat(),
        )
        for e in executions
    ]


@router.post("/pending/{execution_id}")
async def approve_or_reject(
    execution_id: str,
    req: ApprovalAction,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ToolExecution).where(ToolExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    if execution.status != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Execution is not awaiting approval")

    execution.approved_by = user.id

    if req.approved:
        execution.status = "executing"
        await db.flush()

        try:
            tool_result = await registry.execute(execution.tool_name, execution.arguments)
            execution.result = tool_result if isinstance(tool_result, dict) else {"output": str(tool_result)}
            execution.status = "completed"
        except Exception as e:
            execution.error = str(e)
            execution.status = "failed"
    else:
        execution.status = "rejected"

    db.add(AuditLog(
        user_id=user.id,
        action="approval_decision",
        resource_type="tool_execution",
        resource_id=execution_id,
        details={"approved": req.approved, "tool": execution.tool_name, "status": execution.status},
    ))

    await db.commit()
    return {
        "execution_id": execution_id,
        "status": execution.status,
        "result": execution.result,
        "error": execution.error,
    }


@router.post("/batch")
async def batch_approve_reject(
    req: BatchApprovalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    results = []
    for eid in req.execution_ids:
        exec_result = await db.execute(
            select(ToolExecution).where(ToolExecution.id == eid)
        )
        execution = exec_result.scalar_one_or_none()
        if not execution or execution.status != "awaiting_approval":
            results.append({"id": eid, "status": "skipped", "reason": "not found or not pending"})
            continue

        execution.approved_by = user.id

        if req.approved:
            execution.status = "executing"
            await db.flush()
            try:
                tool_result = await registry.execute(execution.tool_name, execution.arguments)
                execution.result = tool_result if isinstance(tool_result, dict) else {"output": str(tool_result)}
                execution.status = "completed"
            except Exception as e:
                execution.error = str(e)
                execution.status = "failed"
        else:
            execution.status = "rejected"

        results.append({"id": eid, "status": execution.status})

    db.add(AuditLog(
        user_id=user.id,
        action="batch_approval",
        details={"approved": req.approved, "count": len(req.execution_ids), "results": results},
    ))

    await db.commit()
    return {
        "processed": len(results),
        "approved": req.approved,
        "results": results,
    }


@router.get("/history")
async def approval_history(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ToolExecution)
        .where(ToolExecution.requires_approval == True)
        .order_by(ToolExecution.created_at.desc())
        .limit(limit)
    )
    executions = result.scalars().all()
    return [
        {
            "id": e.id,
            "tool_name": e.tool_name,
            "arguments": e.arguments,
            "status": e.status,
            "result": e.result,
            "error": e.error,
            "approved_by": e.approved_by,
            "created_at": e.created_at.isoformat(),
        }
        for e in executions
    ]

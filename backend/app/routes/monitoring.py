import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.models import User, Conversation, Message, ToolExecution, AuditLog
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

_start_time = time.time()


@router.get("/health")
async def system_health(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    redis_ok = False
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        redis_ok = True
        await r.close()
    except Exception:
        pass

    return {
        "status": "healthy" if (db_ok and redis_ok) else "degraded",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_seconds,
        "services": {
            "database": "connected" if db_ok else "disconnected",
            "redis": "connected" if redis_ok else "disconnected",
            "openai_model": settings.openai_model,
        },
        "environment": settings.environment,
    }


@router.get("/usage")
async def usage_stats(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_conversations = (await db.execute(
        select(func.count(Conversation.id)).where(Conversation.created_at >= since)
    )).scalar() or 0

    total_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since)
    )).scalar() or 0

    user_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since, Message.role == "user")
    )).scalar() or 0

    assistant_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since, Message.role == "assistant")
    )).scalar() or 0

    tool_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since, Message.role == "tool")
    )).scalar() or 0

    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    return {
        "period_days": days,
        "conversations": total_conversations,
        "total_messages": total_messages,
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "tool_messages": tool_messages,
        "registered_users": total_users,
        "avg_messages_per_conversation": round(total_messages / max(total_conversations, 1), 1),
    }


@router.get("/tools")
async def tool_analytics(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(
            ToolExecution.tool_name,
            func.count(ToolExecution.id).label("total"),
            func.sum(case((ToolExecution.status == "completed", 1), else_=0)).label("succeeded"),
            func.sum(case((ToolExecution.status == "failed", 1), else_=0)).label("failed"),
            func.sum(case((ToolExecution.status == "rejected", 1), else_=0)).label("rejected"),
            func.avg(ToolExecution.duration_ms).label("avg_duration_ms"),
        )
        .where(ToolExecution.created_at >= since)
        .group_by(ToolExecution.tool_name)
        .order_by(func.count(ToolExecution.id).desc())
    )
    rows = result.all()

    tools = []
    total_executions = 0
    total_failures = 0
    for row in rows:
        total = row.total or 0
        succeeded = row.succeeded or 0
        failed = row.failed or 0
        rejected = row.rejected or 0
        total_executions += total
        total_failures += failed
        tools.append({
            "tool_name": row.tool_name,
            "total_executions": total,
            "succeeded": succeeded,
            "failed": failed,
            "rejected": rejected,
            "success_rate": round((succeeded / max(total, 1)) * 100, 1),
            "avg_duration_ms": round(row.avg_duration_ms or 0),
        })

    recent_errors = await db.execute(
        select(ToolExecution.tool_name, ToolExecution.error, ToolExecution.created_at)
        .where(ToolExecution.status == "failed", ToolExecution.created_at >= since)
        .order_by(ToolExecution.created_at.desc())
        .limit(10)
    )
    errors = [
        {"tool": r.tool_name, "error": (r.error or "")[:200], "time": r.created_at.isoformat()}
        for r in recent_errors.all()
    ]

    return {
        "period_days": days,
        "total_executions": total_executions,
        "total_failures": total_failures,
        "overall_success_rate": round(((total_executions - total_failures) / max(total_executions, 1)) * 100, 1),
        "tools": tools,
        "recent_errors": errors,
    }


@router.get("/costs")
async def cost_tracking(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since)
    )).scalar() or 0

    user_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since, Message.role == "user")
    )).scalar() or 0

    assistant_messages = (await db.execute(
        select(func.count(Message.id)).where(Message.created_at >= since, Message.role == "assistant")
    )).scalar() or 0

    user_chars = 0
    result = await db.execute(
        select(func.sum(func.length(Message.content)))
        .where(Message.created_at >= since, Message.role == "user")
    )
    user_chars = result.scalar() or 0

    assistant_chars = 0
    result = await db.execute(
        select(func.sum(func.length(Message.content)))
        .where(Message.created_at >= since, Message.role == "assistant")
    )
    assistant_chars = result.scalar() or 0

    est_input_tokens = int(user_chars / 4)
    est_output_tokens = int(assistant_chars / 4)

    input_cost = est_input_tokens * 2.50 / 1_000_000
    output_cost = est_output_tokens * 10.00 / 1_000_000
    total_cost = input_cost + output_cost

    daily_rate = total_cost / max(days, 1)

    return {
        "period_days": days,
        "estimated_input_tokens": est_input_tokens,
        "estimated_output_tokens": est_output_tokens,
        "estimated_total_tokens": est_input_tokens + est_output_tokens,
        "cost_breakdown": {
            "input_cost_usd": round(input_cost, 4),
            "output_cost_usd": round(output_cost, 4),
            "total_cost_usd": round(total_cost, 4),
        },
        "projections": {
            "daily_avg_usd": round(daily_rate, 4),
            "monthly_projected_usd": round(daily_rate * 30, 2),
        },
        "pricing_note": "Estimates based on GPT-4o pricing ($2.50/1M input, $10/1M output). Actual costs may vary.",
    }


@router.get("/audit")
async def audit_trail(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "action": l.action,
            "resource_type": l.resource_type,
            "resource_id": l.resource_id,
            "details": l.details,
            "time": l.created_at.isoformat(),
        }
        for l in logs
    ]

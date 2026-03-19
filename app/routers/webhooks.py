from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()


def _verify_admin(request: Request, x_admin_key: str) -> None:
    settings = request.app.state.settings
    if not settings.admin_key or x_admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")


class SetTierRequest(BaseModel):
    user_id: str
    tier: str


@router.post("/admin/set-tier")
async def set_tier(
    body: SetTierRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
    x_admin_key: str = Header(...),
):
    """Manually set a user's subscription tier. Protected by admin key."""
    _verify_admin(request, x_admin_key)

    tier_config = request.app.state.tier_config
    if body.tier not in tier_config.tiers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tier: {body.tier}. Available: {list(tier_config.tiers.keys())}",
        )

    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        "UPDATE users SET tier = ?, updated_at = ? WHERE id = ?",
        (body.tier, now, body.user_id),
    )
    await db.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"status": "ok", "user_id": body.user_id, "tier": body.tier}


@router.get("/admin/dashboard")
async def dashboard(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
    x_admin_key: str = Header(...),
    days: int = Query(default=7, ge=1, le=90),
):
    """Admin dashboard: users, usage, costs, latency. Protected by admin key."""
    _verify_admin(request, x_admin_key)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Users ---
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    total_users = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
    active_users = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT tier, COUNT(*) FROM users WHERE is_active = 1 GROUP BY tier"
    )
    tier_breakdown = {row[0]: row[1] for row in await cursor.fetchall()}

    # --- Usage (last N days) ---
    since = f"{days}d"
    cursor = await db.execute(
        """SELECT
            COUNT(*) as total_requests,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
            SUM(CASE WHEN status = 'rate_limited' THEN 1 ELSE 0 END) as rate_limited,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) as total_cost_usd,
            ROUND(AVG(response_time_ms), 0) as avg_latency_ms,
            MAX(response_time_ms) as max_latency_ms,
            MIN(response_time_ms) as min_latency_ms
           FROM usage_log
           WHERE request_timestamp >= date('now', ?)""",
        (f"-{days} days",),
    )
    row = await cursor.fetchone()
    usage_summary = {
        "period_days": days,
        "total_requests": row[0],
        "successful": row[1],
        "errors": row[2],
        "rate_limited": row[3],
        "total_input_tokens": row[4],
        "total_output_tokens": row[5],
        "total_tokens": row[4] + row[5],
        "total_cost_usd": round(row[6], 4),
        "avg_latency_ms": int(row[7]) if row[7] else 0,
        "max_latency_ms": row[8],
        "min_latency_ms": row[9],
    }

    # --- Usage by provider ---
    cursor = await db.execute(
        """SELECT provider, model,
            COUNT(*) as requests,
            COALESCE(SUM(input_tokens), 0) as input_tokens,
            COALESCE(SUM(output_tokens), 0) as output_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) as cost_usd,
            ROUND(AVG(response_time_ms), 0) as avg_latency_ms
           FROM usage_log
           WHERE request_timestamp >= date('now', ?) AND status = 'success'
           GROUP BY provider, model
           ORDER BY requests DESC""",
        (f"-{days} days",),
    )
    by_model = [
        {
            "provider": r[0],
            "model": r[1],
            "requests": r[2],
            "input_tokens": r[3],
            "output_tokens": r[4],
            "cost_usd": round(r[5], 4),
            "avg_latency_ms": int(r[6]) if r[6] else 0,
        }
        for r in await cursor.fetchall()
    ]

    # --- Usage by user (top 10) ---
    cursor = await db.execute(
        """SELECT u.id, u.email, u.tier,
            COUNT(*) as requests,
            COALESCE(SUM(l.input_tokens), 0) + COALESCE(SUM(l.output_tokens), 0) as total_tokens,
            COALESCE(SUM(l.estimated_cost_usd), 0) as cost_usd,
            MAX(l.request_timestamp) as last_request
           FROM usage_log l
           JOIN users u ON l.user_id = u.id
           WHERE l.request_timestamp >= date('now', ?) AND l.status = 'success'
           GROUP BY u.id
           ORDER BY total_tokens DESC
           LIMIT 10""",
        (f"-{days} days",),
    )
    top_users = [
        {
            "user_id": r[0],
            "email": r[1],
            "tier": r[2],
            "requests": r[3],
            "total_tokens": r[4],
            "cost_usd": round(r[5], 4),
            "last_request": r[6],
        }
        for r in await cursor.fetchall()
    ]

    # --- Today's usage ---
    cursor = await db.execute(
        """SELECT
            COUNT(*) as requests,
            COALESCE(SUM(input_tokens), 0) + COALESCE(SUM(output_tokens), 0) as tokens,
            COALESCE(SUM(estimated_cost_usd), 0) as cost_usd
           FROM usage_log
           WHERE request_timestamp >= ? AND status = 'success'""",
        (today,),
    )
    today_row = await cursor.fetchone()
    today_usage = {
        "requests": today_row[0],
        "tokens": today_row[1],
        "cost_usd": round(today_row[2], 4),
    }

    # --- Latency percentiles (last N days) ---
    cursor = await db.execute(
        """SELECT response_time_ms FROM usage_log
           WHERE request_timestamp >= date('now', ?) AND status = 'success'
           ORDER BY response_time_ms""",
        (f"-{days} days",),
    )
    latencies = [r[0] for r in await cursor.fetchall() if r[0] is not None]
    percentiles = {}
    if latencies:
        for p in [50, 75, 90, 95, 99]:
            idx = int(len(latencies) * p / 100)
            percentiles[f"p{p}"] = latencies[min(idx, len(latencies) - 1)]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "users": {
            "total": total_users,
            "active": active_users,
            "by_tier": tier_breakdown,
        },
        "today": today_usage,
        "usage": usage_summary,
        "by_model": by_model,
        "top_users": top_users,
        "latency_percentiles": percentiles,
    }


@router.get("/admin/users")
async def list_users(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
    x_admin_key: str = Header(...),
):
    """List all users with their usage stats."""
    _verify_admin(request, x_admin_key)

    cursor = await db.execute(
        """SELECT u.id, u.apple_sub, u.email, u.tier, u.created_at, u.is_active,
            (SELECT COUNT(*) FROM usage_log l WHERE l.user_id = u.id AND l.status = 'success') as total_requests,
            (SELECT COALESCE(SUM(COALESCE(l2.input_tokens,0)) + SUM(COALESCE(l2.output_tokens,0)), 0)
             FROM usage_log l2 WHERE l2.user_id = u.id AND l2.status = 'success') as total_tokens,
            (SELECT COALESCE(SUM(l3.estimated_cost_usd), 0)
             FROM usage_log l3 WHERE l3.user_id = u.id AND l3.status = 'success') as total_cost_usd,
            (SELECT MAX(l4.request_timestamp) FROM usage_log l4 WHERE l4.user_id = u.id) as last_request
           FROM users u
           ORDER BY u.created_at DESC"""
    )
    users = [
        {
            "id": r[0],
            "apple_sub": r[1][:8] + "..." if r[1] else None,
            "email": r[2],
            "tier": r[3],
            "created_at": r[4],
            "is_active": bool(r[5]),
            "total_requests": r[6],
            "total_tokens": r[7],
            "total_cost_usd": round(r[8], 4) if r[8] else 0,
            "last_request": r[9],
        }
        for r in await cursor.fetchall()
    ]

    return {"users": users, "count": len(users)}

import time

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_db
from app.dependencies import get_current_user
from app.models.chat import ChatRequest, ChatResponse
from app.models.user import UserRecord

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Proxy an LLM request through CloudZap with auth, tier, and rate enforcement."""
    tier_config = request.app.state.tier_config
    provider_router = request.app.state.provider_router
    rate_limiter = request.app.state.rate_limiter
    usage_tracker = request.app.state.usage_tracker
    pricing = request.app.state.pricing

    # 1. Look up tier
    tier = tier_config.tiers.get(user.tier)
    if not tier:
        raise HTTPException(
            status_code=500,
            detail={"code": "invalid_request", "message": f"Unknown tier: {user.tier}"},
        )

    # 2. Resolve "auto" model to tier's default
    if body.model == "auto" or body.provider == "auto":
        if not tier.default_model:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_request",
                    "message": "No default model configured for this tier",
                },
            )
        # Parse "provider/model" from tier config
        parts = tier.default_model.split("/", 1)
        if len(parts) == 2:
            body = body.model_copy(update={"provider": parts[0], "model": parts[1]})
        else:
            body = body.model_copy(update={"model": tier.default_model})

    # 3. Check provider + model access
    usage_tracker.check_model_access(body, tier)

    # 4. Rate limit
    allowed, retry_after = rate_limiter.check(user.id, tier.requests_per_minute)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                "details": {"retry_after": retry_after},
            },
        )

    # 5. Token + cost quota
    await usage_tracker.check_quota(db, user, tier)

    # 6. Route to provider
    start = time.monotonic()
    try:
        response = await provider_router.route(body)
    except HTTPException:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        await usage_tracker.log_usage(
            db, user.id, body, None, elapsed_ms, status="error"
        )
        raise

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # 7. Calculate cost from pricing data
    if pricing.is_loaded:
        cost = pricing.calculate_cost(
            provider=body.provider,
            model=body.model,
            usage=response.usage,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        response.cost = cost

    # 8. Log usage
    await usage_tracker.log_usage(db, user.id, body, response, elapsed_ms)

    return response

import logging
from fastapi import APIRouter, BackgroundTasks, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.models.schemas import EmailSendRequest, EmailSendResponse
from investbrief.web.services.email_sender import send_email_for_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/email", tags=["email"])

RATE_LIMIT_TTL = 300


@router.post("/send", response_model=EmailSendResponse)
def trigger_email(
    body: EmailSendRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    user_markets = list(user.get("markets", {}).keys())
    if body.market and body.market != "all":
        if body.market not in user_markets:
            return EmailSendResponse(status="error", message=f"Market '{body.market}' not configured for this user")
        markets = [body.market]
    else:
        markets = user_markets

    if not markets:
        return EmailSendResponse(status="error", message="No markets configured")

    logger.info(f"[email] user={user.get('name')} id={user['id']} body.market={body.market!r} resolved_markets={markets}")

    for m in markets:
        lock_key = f"email_lock:{user['id']}:{m}"
        if redis.get(lock_key):
            return EmailSendResponse(status="rate_limited", message=f"Please wait before sending another {m} email")
        redis.setex(lock_key, RATE_LIMIT_TTL, "1")

    for i, m in enumerate(markets):
        logger.info(f"[email] adding background task #{i}: market={m}")
        background_tasks.add_task(send_email_for_user, m, user)

    return EmailSendResponse(status="started", message=f"Sending email for: {', '.join(markets)}")

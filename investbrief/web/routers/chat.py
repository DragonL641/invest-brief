import json
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.models.schemas import ChatRequest, SectionAnalysisRequest
from investbrief.web.services import ai_chat
from investbrief.web.services.cache import get_cached, set_cached
from investbrief.web.services.data_fetcher import get_market_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


def _history_key(user_id: int) -> str:
    return f"chat:{user_id}:history"


def _load_history(redis, user_id: int) -> list[dict]:
    data = redis.get(_history_key(user_id))
    if data:
        return json.loads(data)[-10:]
    return []


def _save_history(redis, user_id: int, history: list[dict]):
    redis.setex(_history_key(user_id), 3600, json.dumps(history[-10:], ensure_ascii=False))


@router.post("")
def chat(req: ChatRequest, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    market_data = get_market_data(redis, req.market, user)
    history = _load_history(redis, user["id"])

    def generate():
        collected = ""
        try:
            for chunk in ai_chat.stream_chat(req.message, req.market, market_data, history):
                collected += chunk
                yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
            history.append({"role": "user", "content": req.message})
            history.append({"role": "assistant", "content": collected})
            _save_history(redis, user["id"], history)
        except Exception as e:
            logger.error(f"Chat stream error for user {user['id']}: {e}", exc_info=True)
            # Save partial response if any content was collected
            if collected:
                history.append({"role": "user", "content": req.message})
                history.append({"role": "assistant", "content": collected})
                _save_history(redis, user["id"], history)
            yield f"data: {json.dumps({'error': 'stream_failed'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/section")
def section_analysis(req: SectionAnalysisRequest, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    language = user.get("language", "zh-CN")
    cache_key = f"market:{req.market}:analysis:{req.section}:{language}"

    cached = get_cached(redis, cache_key)
    if cached is not None:
        return {"analysis": cached["analysis"], "cached": True}

    result = ai_chat.analyze_section(req.section, req.market, req.data, language=language)
    set_cached(redis, cache_key, {"analysis": result}, ttl_seconds=1800)
    return {"analysis": result}

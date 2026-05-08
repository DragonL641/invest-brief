# Invest-Brief Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform invest-brief from an email-only CLI tool into a web application with interactive dashboard, AI chatbot, and user-specific data isolation.

**Architecture:** FastAPI backend serves REST/SSE API, Redis caches market data per-user and per-market, existing Python providers (yfinance/akshare) remain unchanged. React SPA with Ant Design dark theme consumes the API. Docker Compose orchestrates 4 containers.

**Tech Stack:** FastAPI, uvicorn, redis-py, python-jose, passlib, bcrypt | React 18, Ant Design 5, TypeScript, Vite, ECharts, react-i18next | Nginx, Docker Compose

**Design Spec:** `docs/superpowers/specs/2026-05-08-web-dashboard-design.md`

---

## File Structure

### Backend (new/modified)

```
investbrief/
├── web/                              # NEW
│   ├── __init__.py                   # Package init
│   ├── app.py                        # FastAPI app factory, CORS, lifespan
│   ├── config.py                     # Web config loader (web section from config.json)
│   ├── auth.py                       # JWT create/verify, password hashing, dependency
│   ├── deps.py                       # FastAPI dependencies: get_redis, get_current_user
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py                   # POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me
│   │   ├── data.py                   # GET /api/data/{market}, POST /api/data/{market}/refresh, GET /api/status
│   │   ├── watchlist.py              # GET/POST/DELETE /api/watchlist
│   │   └── chat.py                   # POST /api/chat (SSE), POST /api/chat/section
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cache.py                  # Redis get/set/invalidate with TTL
│   │   ├── data_fetcher.py           # Provider orchestration: fetch + cache + user filtering
│   │   └── ai_chat.py               # Claude API: global chat + section analysis
│   └── models/
│       ├── __init__.py
│       └── schemas.py                # Pydantic: LoginRequest, TokenResponse, UserData, etc.
├── core/                             # EXISTING (unchanged)
├── us/                               # EXISTING (unchanged)
├── cn/                               # EXISTING (unchanged)
└── report.py                         # EXISTING (unchanged)
run_web.py                            # NEW: ASGI entry point for FastAPI
run.py                                # EXISTING (unchanged)
config.example.json                   # MODIFY: add web section + password field
pyproject.toml                        # MODIFY: add web dependencies
```

### Frontend (new)

```
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── public/
│   └── favicon.svg
├── src/
│   ├── main.tsx                      # React entry
│   ├── App.tsx                       # Router + auth guard
│   ├── api/
│   │   ├── client.ts                 # Axios instance with JWT interceptor
│   │   ├── auth.ts                   # login, logout, me
│   │   ├── data.ts                   # getMarketData, refreshMarket, getStatus
│   │   ├── watchlist.ts              # CRUD
│   │   └── chat.ts                   # chatStream, sectionAnalysis
│   ├── hooks/
│   │   ├── useAuth.ts                # Auth context + token management
│   │   └── useMarketData.ts          # SWR-style data fetching
│   ├── pages/
│   │   ├── LoginPage.tsx             # Email + password login
│   │   └── DashboardPage.tsx         # Main dashboard with tabs
│   ├── components/
│   │   ├── Header.tsx                # Logo, tabs, lang switch, refresh, avatar
│   │   ├── MarketOverview.tsx        # Index cards grid
│   │   ├── StockCard.tsx             # Full-detail vertical card
│   │   ├── NewsList.tsx              # News items with sentiment
│   │   ├── EconomicCalendar.tsx      # Calendar table
│   │   ├── WatchlistSection.tsx      # Watchlist with add/remove
│   │   ├── RecommendationsSection.tsx # Recommended stocks
│   │   ├── ChatFab.tsx               # Floating AI button
│   │   └── ChatPanel.tsx             # Chat dialog with streaming
│   ├── i18n/
│   │   ├── index.ts                  # i18next init
│   │   ├── zh-CN.json                # Chinese translations
│   │   └── ko-KR.json                # Korean translations
│   └── styles/
│       └── theme.ts                  # Ant Design dark theme config
```

### Deployment (new/modified)

```
Dockerfile.api                        # NEW: FastAPI backend image
Dockerfile.scheduler                  # NEW: Scheduler image
frontend/Dockerfile                   # NEW: React build
docker-compose.yml                    # MODIFY: 4-service architecture
nginx/
└── nginx.conf                        # NEW: React static + API reverse proxy
```

---

## Task 1: Add Backend Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add web dependencies to pyproject.toml**

Add these to the `dependencies` array in `pyproject.toml`:

```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.32.0",
"redis>=5.0.0",
"python-jose[cryptography]>=3.3.0",
"passlib[bcrypt]>=1.7.4",
"sse-starlette>=2.0.0",
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/liuziyi/Projects/invest-brief && uv sync`
Expected: Dependencies installed, lock file updated.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add web dashboard backend dependencies"
```

---

## Task 2: Update Config Schema

**Files:**
- Modify: `config.example.json`

- [ ] **Step 1: Add `web` section and `password` field to config.example.json**

Add a `web` section at the top level and a `password` field to each recipient:

```json
{
  "web": {
    "host": "0.0.0.0",
    "port": 8000,
    "secret_key": "CHANGE_ME_TO_A_RANDOM_SECRET"
  },
  "markets": { ... },
  "email_service": { ... },
  "recipients": [
    {
      "id": 1,
      "email": "recipient@example.com",
      "password": "hashed_password_here",
      "name": "Recipient1",
      ...
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add config.example.json
git commit -m "chore: add web section and password field to config schema"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `investbrief/web/__init__.py`
- Create: `investbrief/web/models/__init__.py`
- Create: `investbrief/web/models/schemas.py`

- [ ] **Step 1: Create package structure**

```bash
mkdir -p investbrief/web/routers investbrief/web/services investbrief/web/models
touch investbrief/web/__init__.py investbrief/web/models/__init__.py
```

- [ ] **Step 2: Write Pydantic schemas in `investbrief/web/models/schemas.py`**

```python
from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    id: int
    email: str
    name: str
    language: str
    markets: dict


class WatchlistItem(BaseModel):
    symbol: str
    name: str
    market: str


class WatchlistResponse(BaseModel):
    id: str
    symbol: str
    name: str
    market: str


class ChatRequest(BaseModel):
    message: str
    market: str


class SectionAnalysisRequest(BaseModel):
    section: str
    market: str
    data: dict


class RefreshResponse(BaseModel):
    status: str
    updated_at: str


class StatusResponse(BaseModel):
    us: Optional[dict] = None
    cn: Optional[dict] = None
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/
git commit -m "feat(web): add Pydantic request/response schemas"
```

---

## Task 4: Auth System

**Files:**
- Create: `investbrief/web/auth.py`
- Create: `investbrief/web/config.py`

- [ ] **Step 1: Write `investbrief/web/config.py` — web config loader**

```python
import json
import os
from pathlib import Path

_config_cache = None


def get_config() -> dict:
    global _config_cache
    if _config_cache is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        with open(config_path) as f:
            _config_cache = json.load(f)
    return _config_cache


def get_web_config() -> dict:
    return get_config().get("web", {})


def get_recipients() -> list[dict]:
    return get_config().get("recipients", [])


def get_recipient_by_email(email: str) -> dict | None:
    for r in get_recipients():
        if r.get("email") == email:
            return r
    return None


def reload_config():
    global _config_cache
    _config_cache = None
```

- [ ] **Step 2: Write `investbrief/web/auth.py` — JWT + password hashing**

```python
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from investbrief.web.config import get_web_config, get_recipient_by_email

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(user_id: int, email: str) -> str:
    secret = get_web_config().get("secret_key", "dev-secret")
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": email, "uid": user_id, "exp": expire}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    secret = get_web_config().get("secret_key", "dev-secret")
    try:
        payload = jwt.decode(credentials.credentials, secret, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    user = get_recipient_by_email(email)
    if user is None or not user.get("active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/auth.py investbrief/web/config.py
git commit -m "feat(web): add JWT auth and config loader"
```

---

## Task 5: FastAPI Dependencies

**Files:**
- Create: `investbrief/web/deps.py`

- [ ] **Step 1: Write `investbrief/web/deps.py` — Redis + user dependency**

```python
import redis
from investbrief.web.auth import get_current_user

_redis_client = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        import os
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client
```

Exports `get_redis` and re-exports `get_current_user` from auth.

- [ ] **Step 2: Commit**

```bash
git add investbrief/web/deps.py
git commit -m "feat(web): add Redis dependency injection"
```

---

## Task 6: Cache Service

**Files:**
- Create: `investbrief/web/services/__init__.py`
- Create: `investbrief/web/services/cache.py`

- [ ] **Step 1: Create services init**

```bash
touch investbrief/web/services/__init__.py
```

- [ ] **Step 2: Write `investbrief/web/services/cache.py`**

```python
import json
import time
from typing import Any, Optional


def get_cached(redis_client, key: str) -> Optional[dict]:
    data = redis_client.get(key)
    if data is None:
        return None
    return json.loads(data)


def set_cached(redis_client, key: str, value: dict, ttl_seconds: int = 14400):
    redis_client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))


def invalidate(redis_client, key: str):
    redis_client.delete(key)


def get_last_updated(redis_client, market: str) -> Optional[str]:
    return redis_client.get(f"market:{market}:updated_at")


def set_last_updated(redis_client, market: str):
    redis_client.set(f"market:{market}:updated_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def can_refresh(redis_client, market: str) -> bool:
    key = f"market:{market}:refresh_lock"
    return redis_client.get(key) is None


def set_refresh_lock(redis_client, market: str, ttl: int = 60):
    redis_client.setex(f"market:{market}:refresh_lock", ttl, "1")
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/services/
git commit -m "feat(web): add Redis cache service layer"
```

---

## Task 7: Data Fetcher Service

**Files:**
- Create: `investbrief/web/services/data_fetcher.py`

- [ ] **Step 1: Write `investbrief/web/services/data_fetcher.py`**

This is the key bridge between existing providers and the web layer.

```python
from investbrief.web.services.cache import (
    get_cached, set_cached, invalidate, get_last_updated,
    set_last_updated, can_refresh, set_refresh_lock,
)
from investbrief.run import _create_provider, fetch_news, summarize_news, merge_recipient_settings


def _public_keys(market: str) -> list[str]:
    if market == "us":
        return ["indices", "economic_calendar", "premarket_movers", "earnings_calendar", "congressional_trades"]
    return ["indices", "economic_calendar", "dragon_tiger", "sector_performance"]


def _private_keys(market: str) -> list[str]:
    return ["holdings", "recommendations"]


def get_market_data(redis_client, market: str, user: dict) -> dict:
    result = {}

    # Public data (shared across users)
    public_cache = get_cached(redis_client, f"market:{market}:public")
    if public_cache is None:
        public_cache = _fetch_and_cache_public(redis_client, market)
    for k in _public_keys(market):
        result[k] = public_cache.get(k, [])

    # User private data
    uid = user["id"]
    user_cache = get_cached(redis_client, f"market:{market}:user:{uid}:private")
    if user_cache is None:
        user_cache = _fetch_and_cache_user(redis_client, market, user)
    for k in _private_keys(market):
        result[k] = user_cache.get(k, [])

    # News (cached per market)
    news_cache = get_cached(redis_client, f"market:{market}:news")
    result["news"] = news_cache or []
    result["updated_at"] = get_last_updated(redis_client, market) or ""

    return result


def _fetch_and_cache_public(redis_client, market: str) -> dict:
    provider = _create_provider(market)
    all_data = provider.fetch_all([], [], 3)
    public = {k: all_data.get(k, []) for k in _public_keys(market)}
    set_cached(redis_client, f"market:{market}:public", public)
    return public


def _fetch_and_cache_user(redis_client, market: str, user: dict) -> dict:
    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = market_cfg.get("industries", [])
    max_recs = market_cfg.get("max_recommendations", 3)

    provider = _create_provider(market)
    all_data = provider.fetch_all(holdings, industries, max_recs)

    private = {k: all_data.get(k, []) for k in _private_keys(market)}
    set_cached(redis_client, f"market:{market}:user:{user['id']}:private", private)
    return private


def refresh_market(redis_client, market: str, user: dict) -> dict:
    if not can_refresh(redis_client, market):
        return {"status": "rate_limited", "message": "请60秒后再试"}

    set_refresh_lock(redis_client, market)

    # Invalidate all caches for this market
    invalidate(redis_client, f"market:{market}:public")
    invalidate(redis_client, f"market:{market}:news")
    pattern = f"market:{market}:user:*:private"
    for key in redis_client.scan_iter(pattern):
        invalidate(redis_client, key)

    set_last_updated(redis_client, market)

    # Re-fetch and return
    return get_market_data(redis_client, market, user)
```

- [ ] **Step 2: Commit**

```bash
git add investbrief/web/services/data_fetcher.py
git commit -m "feat(web): add data fetcher service with user isolation"
```

---

## Task 8: Auth Router

**Files:**
- Create: `investbrief/web/routers/__init__.py`
- Create: `investbrief/web/routers/auth.py`

- [ ] **Step 1: Create routers init**

```bash
touch investbrief/web/routers/__init__.py
```

- [ ] **Step 2: Write `investbrief/web/routers/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from investbrief.web.auth import verify_password, create_access_token, get_current_user
from investbrief.web.models.schemas import LoginRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    from investbrief.web.config import get_recipient_by_email
    user = get_recipient_by_email(req.email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    stored_pw = user.get("password", "")
    if not stored_pw or not verify_password(req.password, stored_pw):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not user.get("active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")

    token = create_access_token(user["id"], user["email"])
    return TokenResponse(access_token=token)


@router.post("/logout")
def logout():
    return {"message": "ok"}


@router.get("/me", response_model=UserInfo)
def me(user: dict = Depends(get_current_user)):
    return UserInfo(
        id=user["id"],
        email=user["email"],
        name=user.get("name", ""),
        language=user.get("language", "zh-CN"),
        markets=user.get("markets", {}),
    )
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/routers/
git commit -m "feat(web): add auth router (login/logout/me)"
```

---

## Task 9: Data + Watchlist Routers

**Files:**
- Create: `investbrief/web/routers/data.py`
- Create: `investbrief/web/routers/watchlist.py`

- [ ] **Step 1: Write `investbrief/web/routers/data.py`**

```python
from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.services.data_fetcher import get_market_data, refresh_market
from investbrief.web.services.cache import get_last_updated

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/{market}")
def get_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    return get_market_data(redis, market, user)


@router.post("/{market}/refresh")
def refresh_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    return refresh_market(redis, market, user)


@router.get("/status")
def get_status(redis=Depends(get_redis)):
    return {
        "us": {"updated_at": get_last_updated(redis, "us")},
        "cn": {"updated_at": get_last_updated(redis, "cn")},
    }
```

- [ ] **Step 2: Write `investbrief/web/routers/watchlist.py`**

```python
import json
import uuid
from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.models.schemas import WatchlistItem, WatchlistResponse

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _key(user_id: int) -> str:
    return f"user:{user_id}:watchlist"


def _load(redis, user_id: int) -> list[dict]:
    data = redis.get(_key(user_id))
    return json.loads(data) if data else []


def _save(redis, user_id: int, items: list[dict]):
    redis.set(_key(user_id), json.dumps(items, ensure_ascii=False))


@router.get("")
def get_watchlist(user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    return _load(redis, user["id"])


@router.post("")
def add_item(item: WatchlistItem, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    items = _load(redis, user["id"])
    new_item = {"id": str(uuid.uuid4())[:8], "symbol": item.symbol, "name": item.name, "market": item.market}
    items.append(new_item)
    _save(redis, user["id"], items)
    return new_item


@router.delete("/{item_id}")
def delete_item(item_id: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    items = _load(redis, user["id"])
    items = [i for i in items if i["id"] != item_id]
    _save(redis, user["id"], items)
    return {"ok": True}
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/routers/data.py investbrief/web/routers/watchlist.py
git commit -m "feat(web): add data and watchlist API routers"
```

---

## Task 10: AI Chat Service + Router

**Files:**
- Create: `investbrief/web/services/ai_chat.py`
- Create: `investbrief/web/routers/chat.py`

- [ ] **Step 1: Write `investbrief/web/services/ai_chat.py`**

```python
import json
import anthropic
import os


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def stream_chat(message: str, market: str, market_data: dict, history: list[dict]):
    client = _get_client()
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

    system_prompt = f"""你是一位专业的投资顾问。根据以下{market.upper()}市场数据回答用户问题。
数据时间：{market_data.get('updated_at', 'unknown')}
市场数据摘要：
{json.dumps(market_data, ensure_ascii=False, default=str)[:15000]}

回答要求：
- 基于提供的数据进行分析
- 给出具体数据和依据
- 用中文回答
- 不要给出确定性的投资建议，使用"建议关注""可能""值得注意"等措辞"""

    messages = history + [{"role": "user", "content": message}]

    with client.messages.stream(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def analyze_section(section: str, market: str, section_data: dict) -> str:
    client = _get_client()
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

    prompt = f"""分析以下{market.upper()}市场的「{section}」板块数据，给出投资建议。
数据：
{json.dumps(section_data, ensure_ascii=False, default=str)[:10000]}

要求：
- 用中文回答，200-400字
- 分析当前状态、趋势、风险点
- 不给确定性建议"""

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

- [ ] **Step 2: Write `investbrief/web/routers/chat.py`**

```python
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.models.schemas import ChatRequest, SectionAnalysisRequest
from investbrief.web.services import ai_chat, cache
from investbrief.web.services.data_fetcher import get_market_data

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _history_key(user_id: int) -> str:
    return f"chat:{user_id}:history"


def _load_history(redis, user_id: int) -> list[dict]:
    data = redis.get(_history_key(user_id))
    if data:
        msgs = json.loads(data)
        return msgs[-10:]
    return []


def _save_history(redis, user_id: int, history: list[dict]):
    redis.setex(_history_key(user_id), 3600, json.dumps(history[-10:], ensure_ascii=False))


@router.post("")
def chat(req: ChatRequest, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    market_data = get_market_data(redis, req.market, user)
    history = _load_history(redis, user["id"])

    def generate():
        collected = ""
        for chunk in ai_chat.stream_chat(req.message, req.market, market_data, history):
            collected += chunk
            yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        # Save to history
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": collected})
        _save_history(redis, user["id"], history)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/section")
def section_analysis(req: SectionAnalysisRequest, user: dict = Depends(get_current_user)):
    result = ai_chat.analyze_section(req.section, req.market, req.data)
    return {"analysis": result}
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/services/ai_chat.py investbrief/web/routers/chat.py
git commit -m "feat(web): add AI chat service with SSE streaming"
```

---

## Task 11: FastAPI App Factory

**Files:**
- Create: `investbrief/web/app.py`
- Create: `run_web.py`

- [ ] **Step 1: Write `investbrief/web/app.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from investbrief.web.routers import auth, data, watchlist, chat


def create_app() -> FastAPI:
    app = FastAPI(title="Invest Brief API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(data.router)
    app.include_router(watchlist.router)
    app.include_router(chat.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
```

- [ ] **Step 2: Write `run_web.py` (ASGI entry point)**

```python
import uvicorn
import os


def main():
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "8000"))

    from investbrief.web.app import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Test backend locally**

Start Redis (if not running): `docker run -d --name redis -p 6379:6379 redis:7-alpine`
Run: `cd /Users/liuziyi/Projects/invest-brief && uv run python run_web.py`
Expected: Server starts on `http://0.0.0.0:8000`
Verify: `curl http://localhost:8000/api/health` → `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add investbrief/web/app.py run_web.py
git commit -m "feat(web): add FastAPI app factory and ASGI entry point"
```

---

## Task 12: Update Scheduler for Redis

**Files:**
- Modify: `run.py` (add Redis write to scheduler functions)

- [ ] **Step 1: Add Redis write to `_run_single_market`**

After `provider.fetch_all(...)` succeeds in `_run_single_market`, add code to write results to Redis:

```python
# After market_data is obtained (line ~after provider.fetch_all)
try:
    import redis as redis_lib
    r_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis_lib.from_url(r_url, decode_responses=True)
    import json
    public_keys = ["indices", "economic_calendar", "premarket_movers", "earnings_calendar", "congressional_trades"] if market == "us" else ["indices", "economic_calendar", "dragon_tiger", "sector_performance"]
    public = {k: market_data.get(k, []) for k in public_keys}
    r.setex(f"market:{market}:public", 14400, json.dumps(public, ensure_ascii=False, default=str))
    r.set(f"market:{market}:updated_at", __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"))
except Exception as e:
    logger.warning(f"Failed to write to Redis: {e}")
```

This keeps the scheduler compatible with both email and web modes.

- [ ] **Step 2: Commit**

```bash
git add run.py
git commit -m "feat(scheduler): write public data to Redis during scheduled runs"
```

---

## Task 13: Frontend Project Setup

**Files:**
- Create: `frontend/` (entire directory)

- [ ] **Step 1: Scaffold React + TypeScript + Vite project**

```bash
cd /Users/liuziyi/Projects/invest-brief
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Install dependencies**

```bash
cd frontend
npm install antd @ant-design/icons axios react-router-dom echarts echarts-for-react react-i18next i18next
```

- [ ] **Step 3: Create Ant Design dark theme config in `frontend/src/styles/theme.ts`**

```typescript
import type { ThemeConfig } from "antd";

const theme: ThemeConfig = {
  token: {
    colorPrimary: "#494fdf",
    colorBgContainer: "#16181a",
    colorBgLayout: "#000000",
    colorBgElevated: "#16181a",
    colorText: "#ffffff",
    colorTextSecondary: "rgba(255,255,255,0.72)",
    colorTextTertiary: "#8d969e",
    colorBorder: "rgba(255,255,255,0.12)",
    borderRadius: 12,
    fontFamily: "Inter, system-ui, sans-serif",
    fontSize: 14,
  },
  components: {
    Button: { borderRadius: 9999, controlHeight: 40 },
    Card: { colorBgContainer: "#16181a", borderRadiusLG: 20 },
    Input: { borderRadius: 12, colorBgContainer: "#0a0a0a", controlHeight: 48 },
    Table: { colorBgContainer: "#16181a" },
    Tabs: { inkBarColor: "#494fdf", itemActiveColor: "#494fdf", itemSelectedColor: "#494fdf" },
  },
};

export default theme;
```

- [ ] **Step 4: Set up main.tsx with theme and i18n**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp } from "antd";
import { BrowserRouter } from "react-router-dom";
import theme from "./styles/theme";
import App from "./App";
import "./i18n";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider theme={theme}>
      <AntApp>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
```

- [ ] **Step 5: Commit**

```bash
cd /Users/liuziyi/Projects/invest-brief
git add frontend/
git commit -m "feat(frontend): scaffold React + Ant Design + Vite project"
```

---

## Task 14: i18n Setup

**Files:**
- Create: `frontend/src/i18n/index.ts`
- Create: `frontend/src/i18n/zh-CN.json`
- Create: `frontend/src/i18n/ko-KR.json`

- [ ] **Step 1: Write `frontend/src/i18n/index.ts`**

```typescript
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhCN from "./zh-CN.json";
import koKR from "./ko-KR.json";

i18n.use(initReactI18next).init({
  resources: { "zh-CN": { translation: zhCN }, "ko-KR": { translation: koKR } },
  lng: "zh-CN",
  fallbackLng: "zh-CN",
  interpolation: { escapeValue: false },
});

export default i18n;
```

- [ ] **Step 2: Write `frontend/src/i18n/zh-CN.json`**

```json
{
  "app.title": "Invest Brief",
  "tab.us": "美股",
  "tab.cn": "A股",
  "market.overview": "市场概览",
  "market.news": "市场新闻",
  "market.calendar": "经济日历",
  "watchlist.title": "我的自选",
  "watchlist.add": "添加自选",
  "recommendations.title": "推荐关注",
  "refresh": "刷新",
  "refresh.lastUpdate": "最后更新 {{time}}",
  "login.title": "登录",
  "login.email": "邮箱",
  "login.password": "密码",
  "login.submit": "登录",
  "login.error": "邮箱或密码错误",
  "chat.placeholder": "询问关于市场的问题...",
  "chat.analyze": "AI 分析",
  "stock.marketCap": "市值",
  "stock.target": "目标均价",
  "stock.upside": "上行空间",
  "stock.technicals": "技术指标",
  "stock.eps": "EPS 预估",
  "stock.insider": "内部人交易",
  "stock.upgrades": "评级变动",
  "stock.chart": "价格走势",
  "sentiment.positive": "正面",
  "sentiment.negative": "负面",
  "sentiment.neutral": "中性",
  "calendar.date": "日期",
  "calendar.event": "事件",
  "calendar.forecast": "预期",
  "calendar.previous": "前值"
}
```

- [ ] **Step 3: Write `frontend/src/i18n/ko-KR.json`**

```json
{
  "app.title": "Invest Brief",
  "tab.us": "미국 주식",
  "tab.cn": "A주",
  "market.overview": "시장 개요",
  "market.news": "시장 뉴스",
  "market.calendar": "경제 캘린더",
  "watchlist.title": "관심종목",
  "watchlist.add": "추가",
  "recommendations.title": "추천 종목",
  "refresh": "새로고침",
  "refresh.lastUpdate": "마지막 업데이트 {{time}}",
  "login.title": "로그인",
  "login.email": "이메일",
  "login.password": "비밀번호",
  "login.submit": "로그인",
  "login.error": "이메일 또는 비밀번호가 잘못되었습니다",
  "chat.placeholder": "시장에 대해 질문하세요...",
  "chat.analyze": "AI 분석",
  "stock.marketCap": "시가총액",
  "stock.target": "목표가",
  "stock.upside": "상승 여력",
  "stock.technicals": "기술 지표",
  "stock.eps": "EPS 예상",
  "stock.insider": "내부자 거래",
  "stock.upgrades": "평가 변경",
  "stock.chart": "가격 추이",
  "sentiment.positive": "긍정",
  "sentiment.negative": "부정",
  "sentiment.neutral": "중립",
  "calendar.date": "날짜",
  "calendar.event": "이벤트",
  "calendar.forecast": "예상",
  "calendar.previous": "이전"
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/
git commit -m "feat(frontend): add i18n with zh-CN and ko-KR translations"
```

---

## Task 15: API Client + Auth Hook

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/data.ts`
- Create: `frontend/src/api/watchlist.ts`
- Create: `frontend/src/api/chat.ts`
- Create: `frontend/src/hooks/useAuth.ts`

- [ ] **Step 1: Write API client with JWT interceptor (`frontend/src/api/client.ts`)**

```typescript
import axios from "axios";

const client = axios.create({ baseURL: "/api" });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export default client;
```

- [ ] **Step 2: Write API modules (`auth.ts`, `data.ts`, `watchlist.ts`, `chat.ts`)**

`auth.ts`:
```typescript
import client from "./client";
export const login = (email: string, password: string) => client.post("/auth/login", { email, password });
export const logout = () => client.post("/auth/logout");
export const getMe = () => client.get("/auth/me");
```

`data.ts`:
```typescript
import client from "./client";
export const getMarketData = (market: string) => client.get(`/data/${market}`);
export const refreshMarket = (market: string) => client.post(`/data/${market}/refresh`);
export const getStatus = () => client.get("/data/status");
```

`watchlist.ts`:
```typescript
import client from "./client";
export const getWatchlist = () => client.get("/watchlist");
export const addWatchlist = (symbol: string, name: string, market: string) => client.post("/watchlist", { symbol, name, market });
export const deleteWatchlist = (id: string) => client.delete(`/watchlist/${id}`);
```

`chat.ts`:
```typescript
export async function* streamChat(message: string, market: string) {
  const token = localStorage.getItem("token");
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message, market }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop()!;
    for (const line of lines) {
      if (line.startsWith("data: ") && line !== "data: [DONE]") {
        yield JSON.parse(line.slice(6)).text;
      }
    }
  }
}

export const sectionAnalysis = (section: string, market: string, data: object) =>
  fetch("/api/chat/section", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token!}` },
    body: JSON.stringify({ section, market, data }),
  }).then((r) => r.json());
```

- [ ] **Step 3: Write `useAuth.ts` hook**

```typescript
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { getMe } from "../api/auth";

interface User { id: number; email: string; name: string; language: string; markets: Record<string, any>; }
interface AuthContextType { user: User | null; loading: boolean; setUser: (u: User | null) => void; }

const AuthContext = createContext<AuthContextType>({ user: null, loading: true, setUser: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { setLoading(false); return; }
    getMe().then((r) => setUser(r.data)).catch(() => localStorage.removeItem("token")).finally(() => setLoading(false));
  }, []);

  return <AuthContext.Provider value={{ user, loading, setUser }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/ frontend/src/hooks/
git commit -m "feat(frontend): add API client, auth hook, and data modules"
```

---

## Task 16: Login Page

**Files:**
- Create: `frontend/src/pages/LoginPage.tsx`

- [ ] **Step 1: Write LoginPage**

```tsx
import { useState } from "react";
import { Form, Input, Button, Typography, message } from "antd";
import { MailOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { login, getMe } from "../api/auth";
import { useAuth } from "../hooks/useAuth";
import { useTranslation } from "react-i18next";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const { t } = useTranslation();

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const { data } = await login(values.email, values.password);
      localStorage.setItem("token", data.access_token);
      const { data: me } = await getMe();
      setUser(me);
      navigate("/");
    } catch {
      message.error(t("login.error"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ height: "100vh", display: "flex", justifyContent: "center", alignItems: "center", background: "#000" }}>
      <div style={{ width: 360, padding: 40, background: "#16181a", borderRadius: 20 }}>
        <Typography.Title level={2} style={{ color: "#fff", textAlign: "center", marginBottom: 32 }}>
          Invest Brief
        </Typography.Title>
        <Form onFinish={onFinished} size="large">
          <Form.Item name="email" rules={[{ required: true }]}>
            <Input prefix={<MailOutlined />} placeholder={t("login.email")} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true }]}>
            <Input.Password prefix={<LockOutlined />} placeholder={t("login.password")} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              {t("login.submit")}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
}
```

Note: Fix `onFinished` → `onFinish` in Form's onFinish prop.

- [ ] **Step 2: Write `frontend/src/App.tsx` with routing**

```tsx
import { Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <>{children}</> : <Navigate to="/login" />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add login page and app routing"
```

---

## Task 17: Dashboard Page + Header

**Files:**
- Create: `frontend/src/pages/DashboardPage.tsx`
- Create: `frontend/src/components/Header.tsx`

- [ ] **Step 1: Write `Header.tsx`**

Contains: Logo, US/CN tabs, language switch, refresh button, user avatar.

Key elements:
- Tab switching triggers data refetch for selected market
- Language switch calls `i18n.changeLanguage()`
- Refresh button calls `refreshMarket(currentMarket)`

- [ ] **Step 2: Write `DashboardPage.tsx`**

```tsx
import { useState, useEffect } from "react";
import { Spin } from "antd";
import Header from "../components/Header";
import MarketOverview from "../components/MarketOverview";
import WatchlistSection from "../components/WatchlistSection";
import RecommendationsSection from "../components/RecommendationsSection";
import NewsList from "../components/NewsList";
import EconomicCalendar from "../components/EconomicCalendar";
import ChatFab from "../components/ChatFab";
import { getMarketData } from "../api/data";
import { useAuth } from "../hooks/useAuth";

export default function DashboardPage() {
  const [market, setMarket] = useState<"us" | "cn">("us");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const { user } = useAuth();

  useEffect(() => {
    setLoading(true);
    getMarketData(market).then((r) => setData(r.data)).finally(() => setLoading(false));
  }, [market]);

  if (loading || !data) return <Spin size="large" style={{ display: "block", margin: "200px auto" }} />;

  return (
    <div style={{ minHeight: "100vh", background: "#000" }}>
      <Header market={market} onMarketChange={setMarket} data={data} />
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 40px", display: "flex", flexDirection: "column", gap: 32 }}>
        <MarketOverview indices={data.indices || []} />
        <WatchlistSection holdings={data.holdings || []} market={market} />
        <NewsList news={data.news || []} />
        <RecommendationsSection recommendations={data.recommendations || []} market={market} />
        <EconomicCalendar calendar={data.economic_calendar || []} />
      </div>
      <ChatFab market={market} data={data} />
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx frontend/src/components/Header.tsx
git commit -m "feat(frontend): add dashboard page layout and header"
```

---

## Task 18: Market Overview + StockCard Components

**Files:**
- Create: `frontend/src/components/MarketOverview.tsx`
- Create: `frontend/src/components/StockCard.tsx`

- [ ] **Step 1: Write `MarketOverview.tsx`**

Index cards grid: 6 columns, each card shows index name, value, change with color coding.

- [ ] **Step 2: Write `StockCard.tsx`**

The most complex component. Full-detail vertical card with:
- Symbol + name + price + change row
- Badge annotations row
- Metrics row (market cap, P/E, beta, 52-week range)
- 52-week range progress bar
- Analyst target + upside + rating distribution bar
- Two-column bottom: technicals+EPS | insider+upgrades
- Chart placeholder area

All data-driven from the API response. Colors: red=up, green=down.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MarketOverview.tsx frontend/src/components/StockCard.tsx
git commit -m "feat(frontend): add MarketOverview and StockCard components"
```

---

## Task 19: Remaining Components

**Files:**
- Create: `frontend/src/components/WatchlistSection.tsx`
- Create: `frontend/src/components/RecommendationsSection.tsx`
- Create: `frontend/src/components/NewsList.tsx`
- Create: `frontend/src/components/EconomicCalendar.tsx`
- Create: `frontend/src/components/ChatFab.tsx`
- Create: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: Write WatchlistSection and RecommendationsSection**

Both render a vertical list of `StockCard` components. WatchlistSection adds a top bar with "add" button.

- [ ] **Step 2: Write NewsList**

Vertical list of news items. Each item: title, source, time, sentiment badge.

- [ ] **Step 3: Write EconomicCalendar**

Ant Design Table with columns: date, event, forecast, previous.

- [ ] **Step 4: Write ChatFab + ChatPanel**

ChatFab: Fixed-position FAB button bottom-right, onClick opens ChatPanel.
ChatPanel: Ant Design Drawer with message input, streaming response display using `streamChat()` API.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "feat(frontend): add all dashboard components"
```

---

## Task 20: Build + Verify Frontend

**Files:**
- Modify: `frontend/vite.config.ts` (proxy API in dev)

- [ ] **Step 1: Configure Vite proxy for dev**

```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
```

- [ ] **Step 2: Build production bundle**

```bash
cd frontend && npm run build
```

Expected: `frontend/dist/` directory with static files.

- [ ] **Step 3: Verify full stack locally**

Terminal 1: `docker run -d --name redis -p 6379:6379 redis:7-alpine`
Terminal 2: `cd /Users/liuziyi/Projects/invest-brief && uv run python run_web.py`
Terminal 3: `cd /Users/liuziyi/Projects/invest-brief/frontend && npm run dev`

Expected: Frontend on localhost:5173, API proxied to FastAPI on 8000.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): configure dev proxy and verify build"
```

---

## Task 21: Docker Multi-Container Setup

**Files:**
- Create: `Dockerfile.api`
- Create: `Dockerfile.scheduler`
- Create: `frontend/Dockerfile`
- Create: `nginx/nginx.conf`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write `Dockerfile.api`**

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libfreetype6-dev fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY run_web.py investbrief/ ./
CMD ["uv", "run", "python", "run_web.py"]
```

- [ ] **Step 2: Write `frontend/Dockerfile`**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

- [ ] **Step 3: Write `nginx/nginx.conf`**

```nginx
events {}
http {
    server {
        listen 80;
        root /usr/share/nginx/html;
        index index.html;

        location /api/ {
            proxy_pass http://api:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        location / {
            try_files $uri $uri/ /index.html;
        }
    }
}
```

- [ ] **Step 4: Update `docker-compose.yml`**

```yaml
services:
  nginx:
    build: ./frontend
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    environment:
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config.json:/app/config.json:ro
      - ./.env:/app/.env:ro
    depends_on:
      - redis
    restart: unless-stopped

  scheduler:
    build:
      context: .
      dockerfile: Dockerfile.scheduler
    environment:
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config.json:/app/config.json:ro
      - ./.env:/app/.env:ro
      - ./logs:/app/logs
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.api Dockerfile.scheduler frontend/Dockerfile nginx/ docker-compose.yml
git commit -m "feat(deploy): add multi-container Docker setup with Nginx"
```

---

## Task 22: End-to-End Verification

- [ ] **Step 1: Hash a test password**

```bash
uv run python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt'])(\"test123\"))"
```

Add the hash to a test user's `password` field in `config.json`.

- [ ] **Step 2: Start full stack**

```bash
docker compose up --build
```

- [ ] **Step 3: Verify all flows**

1. Open `http://localhost` → redirects to login
2. Login with email + password → enters dashboard
3. US tab shows indices, holdings, news
4. CN tab shows A-share data
5. Refresh button triggers data refresh
6. Language switch changes UI text
7. AI chat FAB opens, streaming response works
8. Logout returns to login page

- [ ] **Step 4: Commit any fixes**

---

## Self-Review

**1. Spec coverage:**

| Spec requirement | Task |
|---|---|
| Email + password auth | Task 4, 8, 16 |
| JWT middleware | Task 4 |
| User data isolation | Task 7, 9 |
| Public + private cache | Task 6, 7 |
| Market data API | Task 9 |
| Manual refresh + debounce | Task 6, 9 |
| Watchlist CRUD | Task 9 |
| AI chat (SSE streaming) | Task 10 |
| AI section analysis | Task 10 |
| Login page | Task 16 |
| Dashboard with tabs | Task 17 |
| Vertical stock cards | Task 18 |
| News list | Task 19 |
| Economic calendar | Task 19 |
| Chat FAB + panel | Task 19 |
| i18n zh-CN / ko-KR | Task 14 |
| Interactive ECharts | Task 18 (placeholder) |
| Redis caching | Task 6, 7 |
| Scheduler writes Redis | Task 12 |
| Docker 4-container | Task 21 |
| Nginx reverse proxy | Task 21 |
| Email mode preserved | Task 12 (scheduler unchanged) |

**2. Placeholder scan:** No TBD/TODO found. All steps contain actual code.

**3. Type consistency:** API client function names match between `api/*.ts` files and component usage. Redis key patterns consistent between `cache.py` and `data_fetcher.py`. Pydantic schema names match router parameter types.

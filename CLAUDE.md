# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a personalized daily investment briefing platform (US stocks + A-shares) with two delivery channels:
1. **Email pipeline** — generates HTML reports and sends via email (original)
2. **Web dashboard** — FastAPI backend + React frontend for interactive browsing

Uses yfinance/akshare for market data, external APIs for news, and Claude API for summarization and guidance.

## Commands

### Email Pipeline

```bash
uv run run.py --market us --now              # Run US market once (most common)
uv run run.py --market cn --now              # Run A-share market
uv run run.py --market all --now             # Run all markets
uv run run.py --market us --dry-run          # Build report, output JSON, no email
uv run run.py --market us --now --skip-summary  # Skip Claude API calls
uv run run.py --market us                    # Scheduler mode (cron-based)
uv run run.py --market us --now --log-level DEBUG
```

### Web API Server

```bash
uv run python run_web.py                    # Start FastAPI on :8000 (requires Redis)
REDIS_URL=redis://localhost:6379 uv run python run_web.py
```

### Frontend (React)

```bash
cd frontend
npm run dev          # Vite dev server
npm run build        # tsc + vite build
npm run lint         # ESLint
```

### Docker (full stack)

```bash
docker compose up --build                   # All services: nginx + api + scheduler + redis
```

No test suite.

## Configuration

- `config.json` (gitignored) — per-market schedules, recipients (also serve as web users), email settings, web secret key. Copy from `config.example.json`.
- `.env` (gitignored) — API keys (`FINNHUB_KEY`, `ALPHAVANTAGE_KEY`, `TAVILY_KEY`, `SMTP_PASSWORD`, `ANTHROPIC_API_KEY`, `REDIS_URL`). Copy from `.env.example`.
- `ANTHROPIC_AUTH_TOKEN` auto-aliases to `ANTHROPIC_API_KEY`.
- macOS system proxy auto-detected for yfinance/requests.

## Architecture

### Email Pipeline

**Entry point:** `run.py` — monolithic orchestrator with CLI args and scheduler.

Pipeline per market: Load config -> Merge recipients -> Fetch market data -> Fetch news -> Summarize via Claude -> Generate per-section guidance -> Render HTML -> Send email

### Web Dashboard

**Backend** (`investbrief/web/`):

| Layer | File | Role |
|-------|------|------|
| App | `app.py` | FastAPI factory, CORS, mounts routers |
| Auth | `auth.py` | JWT (HS256, 24h expiry), bcrypt passwords, `get_current_user` dependency |
| Config | `config.py` | Reads `config.json`, exposes user lookup |
| Router | `routers/auth.py` | `/api/auth` — login, logout, me |
| Router | `routers/data.py` | `/api/data` — market data + refresh |
| Router | `routers/watchlist.py` | `/api/watchlist` — CRUD |
| Router | `routers/chat.py` | `/api/chat` — SSE streaming + section analysis |
| Service | `services/data_fetcher.py` | Orchestrates providers, splits public/private data, Redis caching (4h TTL) |
| Service | `services/cache.py` | Redis get/set/invalidate/lock wrappers |
| Service | `services/ai_chat.py` | Anthropic SDK streaming chat |
| Models | `models/schemas.py` | Pydantic request/response models |

**Entry point:** `run_web.py` — starts uvicorn with `investbrief.web.app.create_app()`.

**Frontend** (`frontend/`):

- **Framework:** React 19 + Vite 8 + TypeScript 6 + Ant Design 6 (dark theme)
- **Routing:** React Router v7 — `/login` (public), `/` (protected dashboard)
- **State:** React hooks + TanStack-style fetch, no global state library
- **i18n:** i18next (zh-CN default, ko-KR)
- **API:** Axios with JWT interceptor; SSE via native fetch for chat streaming
- **Pages:** `LoginPage`, `DashboardPage` (5 scroll-spy sections: overview, news, calendar, watchlist, recommendations)
- **Auth:** JWT stored in localStorage, `AuthProvider` context validates on mount via `/auth/me`

### Shared Market Providers

Both email and web channels share the same provider layer (`investbrief/us/` and `investbrief/cn/`):

| Package | Module | Role |
|---------|--------|------|
| `core/` | `provider.py` | `MarketProvider` ABC — interface: `get_indices`, `get_holdings_data`, `get_recommendations`, `fetch_all`, `render_section(**kwargs)` |
| `core/` | `charts.py` | matplotlib charts as base64 PNGs, CJK font config |
| `core/` | `mailer.py` | `EmailSender` — SMTP with retry |
| `us/` | `provider.py` | `USMarketProvider` — yfinance-based |
| `us/` | `clients.py` | `YFinanceClient`; Finnhub/Alpha Vantage/Tavily clients |
| `us/` | `news.py` | `DataProvider` — unified news with fallback and scoring |
| `cn/` | `provider.py` | `CNMarketProvider` — AKShare-based with concurrent fetching |
| `cn/` | `client.py` | `AKShareClient` — wraps akshare |
| `report.py` | — | Email template rendering, multi-language via Claude |

### Data Flow (Web)

Request hits `routers/data.py` -> `data_fetcher.py` creates provider -> `provider.fetch_all()` -> result split into public (indices, calendar) and private (holdings, recommendations) -> cached in Redis with per-user keys -> merged on GET response.

### Auth

Users are `recipients[]` in `config.json` with `id`, `email`, `password` (bcrypt hash), `active`, `language`, `markets`. No database — config-file-based. JWT secret from `config.json`'s `web.secret_key` or `JWT_SECRET` env var.

## Key Conventions

- Pipeline is resilient: API failures log warnings and continue with empty data or fallback.
- News scoring: time (25%) + sentiment (10%) + relevance (40%) + source quality (25%).
- Color scheme: Chinese convention — red = up, green = down.
- Adding a new market: implement `MarketProvider` ABC, add to `_create_provider()` in both `run.py` and `data_fetcher.py`, add news fetcher, update config schema.
- CN provider uses `ThreadPoolExecutor` for concurrent per-stock data fetching.
- Web cache TTL: 4 hours, refresh has 60s rate limit lock.
- Chat model: configurable via `ANTHROPIC_DEFAULT_SONNET_MODEL`, defaults to `claude-sonnet-4-6`.
- Previews saved to `reports/preview_{market}.html` after each email run.

## Deployment

### Full Stack (docker-compose.yml)

4 services: `nginx` (serves frontend + proxies `/api/`), `api` (FastAPI), `scheduler` (email cron), `redis` (cache + auth). Config and `.env` mounted read-only.

### Scheduler Only (docker-compose.deploy.yml)

Single container for email pipeline only. Pulls from GHCR.

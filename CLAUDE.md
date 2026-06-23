# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a personalized daily investment briefing platform (US stocks + A-shares) delivered via:
1. **Email pipeline** — generates HTML reports and sends via scheduled cron
2. **Web dashboard** — FastAPI backend + React frontend for interactive browsing

Uses yfinance/akshare for market data, external APIs for news, and Claude API for summarization and guidance.

## Commands

```bash
# Email pipeline
uv run run.py --market us --now              # Run US market once (most common)
uv run run.py --market cn --now              # Run A-share market
uv run run.py --market all --now             # Run all markets
uv run run.py --market us --dry-run          # Build report, output JSON, no email
uv run run.py --market us --now --skip-summary  # Skip Claude API calls
uv run run.py --market us                    # Scheduler mode (cron-based)
uv run run.py --market us --now --log-level DEBUG

# Web API server (requires Redis)
uv run python run_web.py
REDIS_URL=redis://localhost:6379 uv run python run_web.py

# Frontend
cd frontend
npm run dev          # Vite dev server
npm run build        # tsc + vite build
npm run lint         # ESLint

# Docker
docker compose up --build                   # Local dev: build from source
docker compose -f docker-compose.prod.yml up -d  # Production: pull GHCR images
```

No test suite.

## Configuration

- `config.json` (gitignored) — per-market schedules, recipients (also serve as web users), email settings, web secret key. Copy from `config.example.json`.
- `.env` (gitignored) — API keys (`FINNHUB_KEY`, `ALPHAVANTAGE_KEY`, `TAVILY_KEY`, `SMTP_PASSWORD`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `REDIS_URL`). Copy from `.env.example`.
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
| App | `app.py` | FastAPI factory, CORS, mounts routers, `/api/health` endpoint |
| Auth | `auth.py` | JWT (HS256, 24h expiry), bcrypt passwords, `get_current_user` dependency |
| Config | `config.py` | Reads `config.json`, user lookup, `update_recipient()` with file-locking atomic writes |
| Deps | `deps.py` | `get_redis()` singleton dependency injection |
| Router | `routers/auth.py` | `/api/auth` — login, logout, me |
| Router | `routers/data.py` | `/api/data` — SSE streaming, per-section fetch/refresh, `ThreadPoolExecutor` |
| Router | `routers/stocks.py` | `/api/stocks` — stock search, industry listing (GICS/SW) |
| Router | `routers/chat.py` | `/api/chat` — SSE streaming + section analysis |
| Router | `routers/preferences.py` | `/api/preferences` — CRUD for user holdings/industries/delivery |
| Router | `routers/email.py` | `/api/email` — on-demand email delivery with 5-min rate limit |
| Router | `routers/etf.py` | `/api/etf` — CN-ETF search/analyze/batch + per-user watchlist CRUD (separate from `SECTION_CONFIG`) |
| Service | `services/data_fetcher.py` | Orchestrates providers via `SECTION_CONFIG`, SSE streaming, error classification |
| Service | `services/cache.py` | Redis get/set with whole-market and per-section variants, refresh locks |
| Service | `services/ai_chat.py` | Anthropic SDK streaming chat |
| Service | `services/email_sender.py` | Runs full email pipeline for a single user/market on demand |
| Models | `models/schemas.py` | Pydantic request/response models |

**Entry point:** `run_web.py` — starts uvicorn with `investbrief.web.app.create_app()`.

### Per-Section Data Architecture

`data_fetcher.py` defines a `SECTION_CONFIG` registry that maps each section to a provider method with individual TTLs:

| Market | Public sections | Private (per-user) sections |
|--------|----------------|---------------------------|
| US | `indices` (5m), `economic_calendar` (4h), `premarket_movers` (5m), `earnings_calendar` (4h), `congressional_trades` (4h) | `holdings` (10m), `recommendations` (30m) |
| CN | `indices` (5m), `economic_calendar` (4h), `dragon_tiger` (1h), `sector_performance` (30m) | `holdings` (10m), `recommendations` (30m) |

- News is cached per-language (1h TTL) with Claude-powered translation
- SSE endpoint `GET /api/data/{market}/stream` delivers sections incrementally
- Per-section refresh: `POST /api/data/{market}/refresh/{section}`
- Errors return structured `{reason, retryable, suggestion_key}` responses

### Shared Market Providers

Both email and web channels share `investbrief/us/` and `investbrief/cn/`:

| Package | Module | Role |
|---------|--------|------|
| `core/` | `provider.py` | `MarketProvider` ABC — interface: `get_indices`, `get_holdings_data`, `get_recommendations`, `fetch_all`, `render_section`, `get_section_data` |
| `core/` | `charts.py` | matplotlib charts as base64 PNGs, CJK font config |
| `core/` | `mailer.py` | `EmailSender` — SMTP with retry |
| `core/` | `guards.py` | Validation guards for provider data |
| `us/` | `provider.py` | `USMarketProvider` — yfinance-based |
| `us/` | `clients.py` | `YFinanceClient`; Finnhub/Alpha Vantage/Tavily clients |
| `us/` | `news.py` | `DataProvider` — unified news with fallback and scoring |
| `us/` | `calendar.py` | US economic calendar (FOMC, CPI, NFP, PCE) |
| `us/` | `congress.py` | Congressional trading tracker (house/senate stock watcher) |
| `us/` | `watchlist.py` | Industry-based stock watchlists |
| `us/` | `industries.py` | GICS sector definitions and migration map |
| `cn/` | `provider.py` | `CNMarketProvider` — AKShare-based with concurrent fetching |
| `cn/` | `client.py` | `AKShareClient` — wraps akshare (A-share + ETF spot/history/valuation, full-universe `_DataFrameCache`) |
| `cn/` | `news.py` | A-share news via AKShare |
| `cn/` | `calendar.py` | A-share economic calendar (LPR, PMI, CPI/PPI, M2) |
| `cn/` | `watchlist.py` | AKShare sector name mappings |
| `cn/` | `industries.py` | 31 Shenwan L1 industry classifications and migration map |
| `report.py` | — | Email template rendering, multi-language via Claude |

### ETF Analysis Subsystem

A self-contained **CN-ETF** analysis feature, architecturally separate from `SECTION_CONFIG` — it has its own router, thread pool (`ThreadPoolExecutor`), cache namespace (`etf:analyze:{symbol}`), and a 5-stage pipeline. It does **not** touch `data_fetcher.py`.

**Backend** (`investbrief/etf/`):

| Module | Role |
|--------|------|
| `analyzer.py` | `ETFAnalyzer.analyze(symbol)` — orchestrates the 5 stages, returns `ETFAnalysisResult` (price, IOPV, premium, flows, matched rules, dimension summary, AI conclusion) |
| `indicators.py` | Computes technical indicators from OHLCV history (MA/MACD/RSI/Bollinger/returns/volume/new-high-low) into a flat dict keyed by rule variable names |
| `engine.py` | `RuleEngine` — loads `rules.json`, evaluates each rule via **restricted `eval`** (namespace = `_SAFE_BUILTINS` + data dict only; `__builtins__` stripped) |
| `rules.json` | 23 rules across 4 dimensions — 技术面 / 趋势面 / 资金面 / 估值面; each has `condition` (Python expr over indicator vars), `signal` (bullish/bearish/warning/neutral), `weight` |

**Pipeline:** spot quote + (parallel via thread pool) history K-line + index valuation → `compute_indicators()` → flat data dict → `RuleEngine.evaluate()` → matched rules + per-dimension summary → Claude synthesis (`_ai_synthesize`; falls back to a rule-count conclusion if the API call fails).

**Router** `routers/etf.py` (`/api/etf`):
- `GET /search?q=` — unauthenticated ETF search by code/name
- `GET /analyze/{symbol}` — full analysis, cached 5 min, requires auth
- `GET /batch?symbols=a,b,c` — batch summary (one spot call + cached per-symbol analyses, max 10)
- `GET / POST / DELETE /watchlist[/{symbol}]` — per-user watchlist, stored as `etf_watchlist[]` on the recipient in `config.json` (written via `update_recipient()`)

**Data source:** ETF methods on `AKShareClient` (`get_etf_spot`, `get_etf_spot_batch`, `get_etf_hist` with NAV fallback via `get_etf_nav_history`, `get_index_valuation` → 乐咕乐股 PE percentile). The full ETF universe is cached 5 min in `_DataFrameCache` via `_get_all_etf_df()`.

**Frontend:** `api/etf.ts` + components `ETFCard`, `ETFDetail`, `ETFWatchlist`, rendered inside `DashboardPage` (no separate route).

**Security note:** Rule conditions run through restricted `eval`. Only extend `rules.json` with safe comparison expressions; never loosen the `_SAFE_BUILTINS` whitelist and never feed untrusted input into the condition namespace.

### Data Flow (Web)

1. `GET /api/data/{market}` — `data_fetcher.get_market_data()` iterates `SECTION_CONFIG`, fetches each section (cache-first), merges public + private results
2. `GET /api/data/{market}/stream` — SSE: `fetch_single_section()` per section, yields `data: {section, result}` events
3. `POST /api/data/{market}/refresh/{section}` — invalidates section cache, re-fetches single section
4. Provider `get_section_data(name)` dispatches to the method defined in `SECTION_CONFIG`

### Auth

Users are `recipients[]` in `config.json` with `id`, `email`, `password` (bcrypt hash), `active`, `language`, `markets`, plus optional `holdings`/`industries` (preferences) and `etf_watchlist` (ETF feature). No database — config-file-based. JWT secret from `config.json`'s `web.secret_key` or `JWT_SECRET` env var. Config writes use `filelock` for atomic updates.

### Frontend (`frontend/`)

- **Framework:** React 19 + Vite 8 + TypeScript + Ant Design 6 (dark theme)
- **Routing:** React Router v7 — `/login` (public), `/` (protected dashboard)
- **State:** React hooks + per-section state via `SectionState<T>` type, no global state library
- **i18n:** i18next (zh-CN default, ko-KR)
- **API:** Axios with JWT interceptor; SSE via native fetch for chat/data streaming
- **Pages:** `LoginPage`, `DashboardPage` (scroll-spy sections: overview, news, calendar, watchlist, recommendations; ETF watchlist + detail panel rendered within)
- **Auth:** JWT in localStorage, `AuthProvider` context validates on mount via `/auth/me`

## Key Conventions

- Pipeline is resilient: API failures log warnings and continue with empty data or fallback.
- News scoring: time (25%) + sentiment (10%) + relevance (40%) + source quality (25%).
- Color scheme: Chinese convention — red = up, green = down.
- Adding a new market: implement `MarketProvider` ABC, add to `_create_provider()` in both `run.py` and `data_fetcher.py`, add entry to `SECTION_CONFIG`, add news fetcher, update config schema.
- ETF analysis bypasses `SECTION_CONFIG`/`data_fetcher.py` entirely; it is a standalone router + `investbrief/etf/` pipeline. Adjusting analysis logic = edit `rules.json` (rules), `indicators.py` (metric inputs), or `analyzer.py._ai_synthesize` (AI prompt).
- CN provider uses `ThreadPoolExecutor` for concurrent per-stock data fetching.
- Web cache: per-section TTLs (see SECTION_CONFIG above), refresh has rate limit locks.
- Chat model: configurable via `ANTHROPIC_DEFAULT_SONNET_MODEL`, defaults to `claude-sonnet-4-6`.
- Previews saved to `reports/preview_{market}.html` after each email run.
- Error responses: structured with `reason` (timeout/network/rate_limited/auth/api_error/unknown), `retryable`, and `suggestion_key` for i18n.

## CI/CD

### PR Check (`.github/workflows/pr-check.yml`)
Triggers on `pull_request` to main:
- Frontend: `npm ci` + `npm run lint` + `npm run build`
- Backend: `uv sync --frozen` (lockfile consistency)

### Docker Publish (`.github/workflows/docker-publish.yml`)
Triggers on `push` to main (ignoring docs/config examples). Builds 3 multi-arch (amd64+arm64) images via matrix strategy:
- `ghcr.io/dragonl641/invest-brief` — scheduler (email pipeline)
- `ghcr.io/dragonl641/invest-brief-api` — FastAPI backend
- `ghcr.io/dragonl641/invest-brief-frontend` — nginx + React SPA

Tags: `latest`, commit SHA, `YYYYMMDD` date. Includes Trivy vulnerability scan with SARIF upload to GitHub Security.

## Deployment

### Local Development (`docker-compose.yml`)
Builds all services from source. 4 services: `nginx` (frontend + API proxy), `api` (FastAPI), `scheduler` (email cron), `redis`. Config and `.env` mounted read-only.

### Production (`docker-compose.prod.yml`)
Pulls pre-built images from GHCR. Same 4 services with Redis health check and condition-based startup ordering.

```bash
# Deploy
docker compose -f docker-compose.prod.yml up -d
# Update
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

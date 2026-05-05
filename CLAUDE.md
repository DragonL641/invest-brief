# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a Python tool that generates personalized daily investment briefings (US stocks + A-shares) and delivers them via email. Uses yfinance/akshare for market data, external APIs for news, and Claude API for news summarization and per-section investment guidance.

## Commands

```bash
uv run run.py --market us --now              # Run US market once (most common)
uv run run.py --market cn --now              # Run A-share market
uv run run.py --market all --now             # Run all markets
uv run run.py --market us --dry-run          # Build report, output JSON, no email
uv run run.py --market us --now --skip-summary  # Skip Claude API calls
uv run run.py --market us                    # Scheduler mode (cron-based)
uv run run.py --market us --now --log-level DEBUG
```

No test suite. No linter.

## Configuration

- `config.json` (gitignored) — per-market schedules, recipients with per-market holdings/industries, email service. Copy from `config.example.json`.
- `.env` (gitignored) — API keys (`FINNHUB_KEY`, `ALPHAVANTAGE_KEY`, `TAVILY_KEY`, `SMTP_PASSWORD`, `ANTHROPIC_API_KEY`). Copy from `.env.example`.
- Environment variables override config values for API keys.
- `ANTHROPIC_AUTH_TOKEN` auto-aliases to `ANTHROPIC_API_KEY`.
- macOS system proxy auto-detected for yfinance/requests.

## Architecture

**Entry point:** `run.py` — monolithic orchestrator containing pipeline logic, Claude prompts, CLI args, and scheduler. Pipeline per market:

1. Load config → 2. Merge recipients → 3. Fetch market data → 4. Fetch news → 5. Summarize news via Claude → 6. Generate per-section guidance via Claude → 7. Render HTML → 8. Send email

**Package structure (`investbrief/`):**

| Package | Module | Role |
|---------|--------|------|
| `core/` | `provider.py` | `MarketProvider` ABC — interface: `get_indices`, `get_holdings_data`, `get_recommendations`, `fetch_all`, `render_section(**kwargs)` |
| `core/` | `charts.py` | matplotlib charts as base64 PNGs, CJK font config |
| `core/` | `models.py` | Pydantic models for Claude API JSON validation (`NewsSummaryResponse`) |
| `core/` | `mailer.py` | `EmailSender` — SMTP with retry, multi-provider (QQ/Gmail/Outlook/163) |
| `us/` | `provider.py` | `USMarketProvider` — yfinance-based: indices, holdings with analyst targets/EPS/insider trades, rule-based stock annotations |
| `us/` | `clients.py` | `YFinanceClient`; Finnhub/Alpha Vantage/Tavily clients with `enabled` flags |
| `us/` | `news.py` | `DataProvider` — unified news with fallback priorities and scoring |
| `us/` | `watchlist.py` | Curated stock lists per industry |
| `us/` | `calendar.py` / `insider.py` / `congress.py` | Earnings calendar, EDGAR Form 4, congressional trading |
| `cn/` | `provider.py` | `CNMarketProvider` — AKShare-based with concurrent data fetching, dragon tiger list, rule-based stock annotations |
| `cn/` | `client.py` | `AKShareClient` — wraps akshare for A-share data |
| `cn/` | `news.py` / `watchlist.py` / `calendar.py` | CN news, stock lists, economic calendar |
| `report.py` | — | Template rendering (`{{placeholder}}` on `templates/email_base.html`), multi-language (zh-CN/ko-KR) via Claude translation |

**Data flow:** `run.py` builds `report_data` dict → `report.py` renders HTML → `mailer.py` sends. Each provider independently handles data fetching and HTML rendering including per-section guidance tips and stock annotations.

**Per-section guidance:** Single Claude API call (`generate_section_guidance` in `run.py`) generates investment tips for `market_overview`, `holdings`, and `recommendations` sections. Each provider's `render_section(guidance=...)` inserts these as small gray text blocks. Skipped with `--skip-summary`.

**Stock annotations:** Rule-driven (no API cost). Both providers' `_render_stock_card` checks RSI, MACD, insider trades, target upside, earnings proximity, etc. and renders colored badge tags. US provider also checks earnings calendar proximity via `earnings_symbols` param.

## Key Conventions

- Pipeline is resilient: individual API failures log warnings and continue with empty data or fallback.
- News scoring: time (25%) + sentiment (10%) + relevance (40%) + source quality (25%).
- Color scheme: Chinese convention — red = up, green = down.
- Adding a new market: implement `MarketProvider` ABC, add to `_create_provider()` in `run.py`, add news fetcher, update config schema.
- Recipient config supports both old-style (`settings`) and new-style (`markets.us`/`markets.cn`).
- CN provider uses `ThreadPoolExecutor` for concurrent per-stock data fetching.
- `render_section` uses `**kwargs` in the ABC; concrete implementations use named keyword args (e.g., `guidance`).
- Previews saved to `reports/preview_{market}.html` after each run.

## Deployment

Docker via `Dockerfile` + `docker-compose.yml`. Mounts `config.json` and `.env` as read-only volumes, `logs/` for output. Default timezone: Asia/Shanghai. Scheduler mode by default.

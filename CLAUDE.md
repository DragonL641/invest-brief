# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a macro-economic market report app that generates a daily **US+CN dual-view** briefing and sends it via email (SMTP). Pure backend (no web layer).

- Each trading day: fetch US+CN macro data (rates, monetary aggregates, broad assets, economic calendar, news) → Claude generates a core-view summary + risk outlook → render a merged dual-view HTML report → send one email to all active recipients.
- Data sources: yfinance (US), akshare (CN), external news APIs, Claude for synthesis.
- An ETF analysis package (`investbrief/etf/`) is retained as a standalone asset for future use; it is NOT wired into the email pipeline.

## Commands

```bash
# Email pipeline (the only entry point)
uv run run.py --dry-run                  # Build merged macro report, output JSON to stdout, no email
uv run run.py --dry-run --skip-summary   # Skip Claude ①⑥ (faster, structure-only)
uv run run.py --now                      # Run once: build + send email
uv run run.py --update                   # Refresh macro data into SQLite only, no render/email
uv run run.py                            # Scheduler mode (cron-based, single merged report)

# Data backfill (first deploy only, ~10-30 min)
uv run python scripts/backfill_macro_data.py        # Full-history backfill (CN+US)
uv run python scripts/backfill_macro_data.py --market cn

# Tests
uv run pytest tests/                                # all tests
uv run pytest tests/test_data_layer.py -v           # data layer (BaseData/CNData/USData)
uv run pytest tests/test_provider_contract.py -v    # provider return-shape contracts

# Docker
docker compose up --build                # Local: build scheduler from source
docker compose -f docker-compose.prod.yml up -d  # Prod: pull GHCR image
```

`--market {us,cn,all}` is accepted but **deprecated** — the report is always a merged US+CN single email regardless.

## Configuration

- `config.json` (gitignored) — `markets` (cron schedules), `email_service` (SMTP), `recipients[]`. Copy from `config.example.json`.
- **Schedule:** the scheduler honors the FIRST cron entry of the FIRST enabled market (us preferred). Since the macro pipeline always merges US+CN, keep one schedule entry per market — only the first enabled market's cron actually triggers runs.
- `recipients[]` shape: `{email, name, active, language}`. No web fields (no id/password/markets.holdings).
- `.env` (gitignored) — `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` (defaults to `claude-sonnet-4-6`; set to a model code your `ANTHROPIC_BASE_URL` supports), `SMTP_PASSWORD`, and news keys (`FINNHUB_KEY`, `ALPHAVANTAGE_KEY`, `TAVILY_KEY`).
- `ANTHROPIC_AUTH_TOKEN` auto-aliases to `ANTHROPIC_API_KEY`.
- macOS system proxy auto-detected for yfinance; NO_PROXY set for akshare (eastmoney) domains.

## Architecture

### Email Pipeline (the only channel)

**Entry point:** `run.py` — `_run_macro_report(args)` builds ONE merged US+CN report.

Pipeline: `load config` → fetch US macro (`USMarketProvider`) + CN macro (`CNMarketProvider`) + news → Claude generates ① core view (detailed multi-point) + ⑥ risk → `render_section` (US + CN) → `render_template` → `send_report` (one email). On `--dry-run`, prints JSON instead of sending.

Key `run.py` functions: `_run_macro_report`, `generate_macro_brief` (Claude ①⑥, via `core.llm.get_client`), `_serialize_macro_context`, `fetch_news`, `send_report`, `run_scheduler` / `_run_scheduled_macro` (single cron thread → `_run_macro_report`).

### Data Layer (stateful, P1)

`investbrief/data/` — SQLite-backed macro data layer (ported from StockCycleRiskDetector). The single source of truth for index/macro time series; providers no longer fetch live.

- `base.py` — `BaseData`: schema (`cn_index_daily` / `us_index_daily` / `macro_data` / `sentiment_data` / `update_log`), `upsert_df` / `query` / `merge_sentiment_row` / `latest_bars(table, code, n)` / `latest_macro(indicator, country)` / `_retry_api`.
- `cn_data.py` — `CNData`: 5 A-share indices (`INDEX_CODES`) + LPR/M2/M1/社融/CN10Y/USDCNY (akshare + yfinance).
- `us_data.py` — `USData`: 11 symbols (`INDEX_SYMBOLS`: `^GSPC`/`^IXIC`/`^DJI`/`^VIX`/`^TNX`/`^FVX`/`^IRX`/`HYG`/`CL=F`/`DX-Y.NYB`/`GC=F`) + CPI/GDP.

DB at `data/macro_data.db` (gitignored; parent dir auto-created by `BaseData.conn`). Flow: provider `refresh()` → `data.update_incremental()` (per-method try/except, resilient), then `get_*` read latest bars/values. **Refresh failure → fall back to stored latest** (pipeline never blocks on one API; this is a resilience gain over the pre-P1 live-fetch path). First deploy: `scripts/backfill_macro_data.py`; daily补数: `uv run run.py --update`. Constants in `investbrief/config.py` (`DB_PATH`, `API_RETRY_*`, `US_GDP_BASE_*`).

### Providers

`investbrief/core/provider.py` — `MarketProvider` ABC: `get_indices`, `get_monetary_policy`, `get_asset_performance`, `fetch_all`, `render_section`.

| Package | Module | Role |
|---------|--------|------|
| `core/` | `provider.py` | `MarketProvider` ABC (macro methods) |
| `core/` | `llm.py` | `get_client()` cached Anthropic client + `default_model()` |
| `core/` | `mailer.py` | `EmailSender` — SMTP with retry |
| `data/` | `base.py`/`cn_data.py`/`us_data.py` | **Stateful SQLite data layer** (P1) — providers read index/macro series from here; see Data Layer above |
| `us/` | `provider.py` | `USMarketProvider` — yfinance macro (indices, yields, gold) |
| `us/` | `clients.py` | `YFinanceClient` + Finnhub/Alpha Vantage/Tavily clients |
| `us/` | `news.py` | `DataProvider` — unified news with fallback and scoring |
| `us/` | `calendar.py` | US economic calendar (FOMC/CPI/NFP/PCE) via yfinance + rules |
| `cn/` | `provider.py` | `CNMarketProvider` — akshare macro (indices, LPR/M2/社融/国债, USDCNY) |
| `cn/` | `client.py` | `AKShareClient` — wraps akshare (macro monetary, ETF, index valuation) |
| `cn/` | `news.py` | A-share news via AKShare |
| `cn/` | `calendar.py` | A-share economic calendar (LPR/PMI/CPI/PPI/M2) |
| `etf/` | — | **Retained ETF analysis package** (analyzer/engine/indicators/rules.json); not wired into pipeline |
| `report.py` | — | Template-rendering library: `load_template` / `render_template` / `translate_html` (multi-language via Claude) |

### Macro data sources (verified)

- US rates: yfinance `^TNX`(10Y), `^FVX`(5Y), `^IRX`(13W); broad assets: `^GSPC`/`^IXIC`/`^DJI`/`^VIX`/`CL=F`/`DX-Y.NYB`/`GC=F`(gold). Fed funds target = static constant (update on FOMC).
- CN monetary: akshare `macro_china_lpr` (LPR1Y/5Y), `macro_china_money_supply` (M2/M1 YoY), `macro_china_shrzgm` (社融), `bond_china_yield` (CN 10Y, filter 中债国债收益率曲线); FX: yfinance `USDCNY=X`.
- **akshare frames are inconsistently ordered** — always sort by date/month column descending for latest, never rely on position.
- CN-US yield spread is inferred by Claude from US 10Y and CN 10Y (both passed through separately by the pipeline; no explicit subtraction is computed).

### Report structure (email)

`templates/email_base.html`: header (宏观日报 title) → ① 核心观点 (`.summary-box`, Claude) → `{{market_sections}}` (US section + CN section, each: 大类资产 / 货币政策 / 经济日历) → ⑥ 风险提示与下周关注 → news → footer. `report.render_template` replaces `{{macro_summary}}`/`{{risk_outlook}}`/`{{market_sections}}`/`{{global_news}}` etc.

## Key Conventions

- Pipeline is resilient: API failures log warnings and continue with empty data / fallback. Claude failure → ①⑥ use placeholder strings, report still sends.
- Color scheme: Chinese convention — red = up, green = down (`#e74c3c` / `#27ae60`).
- Adding a new macro section: add a `get_*` method to `MarketProvider` ABC + US/CN implementations + a `_render_*` helper + call in `render_section` + include in `_serialize_macro_context` for Claude.
- Anthropic client: always via `investbrief.core.llm.get_client()` (don't construct `anthropic.Anthropic(...)` inline).
- Previews saved to `reports/preview_macro.html` after each non-dry-run.
- Model configurable via `ANTHROPIC_DEFAULT_SONNET_MODEL`.

## CI/CD

### PR Check (`.github/workflows/pr-check.yml`)
`pull_request` to main → `uv sync --frozen` (lockfile consistency) + `uv run pytest tests/ -q`.

### Docker Publish (`.github/workflows/docker-publish.yml`)
`push` to main → builds ONE multi-arch (amd64+arm64) image: `ghcr.io/dragonl641/invest-brief` (scheduler). Trivy scan + SARIF.

## Deployment

### Local (`docker-compose.yml`)
Single `scheduler` service, builds from `Dockerfile.scheduler`. Mounts config.json/.env (ro), logs/, reports/, data/ (stateful SQLite, P1).

### Prod (`docker-compose.prod.yml`)
Pulls `ghcr.io/dragonl641/invest-brief:latest`. Same mounts.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

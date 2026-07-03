# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a macro-economic market report app that generates a daily **US+CN dual-view** briefing and sends it via email (SMTP). Pure backend (no web layer).

- Each trading day: fetch US+CN macro data (rates, monetary aggregates, broad assets, economic calendar, news) → Claude generates a core-view summary + risk outlook → render a merged dual-view HTML report → send one email to all active recipients.
- Data sources: yfinance (US), akshare (CN), external news APIs, Claude for synthesis.
- Two email types: the **macro email** (daily, broadcast to all active recipients) and the optional **holdings email** (per-recipient, sent only to recipients who configure a `holdings` list). The `investbrief/etf/` package is reused by the holdings pipeline for CN ETF analysis.

## Commands

```bash
# Email pipeline (the only entry point)
uv run run.py --dry-run                  # Build merged macro report, output JSON to stdout, no email
uv run run.py --dry-run --skip-summary   # Skip Claude ①⑥ (faster, structure-only)
uv run run.py --now                      # Run once: build + send email
uv run run.py --update                   # Refresh macro data into SQLite only, no render/email
uv run run.py                            # Scheduler mode (cron-based; runs macro then holdings)
# --only {macro,holdings} limits a single run to one pipeline (default: both)
uv run run.py --dry-run --only holdings  # Build per-recipient holdings email (needs recipients[].holdings)

# Data backfill (first deploy only, ~10-30 min)
uv run python scripts/backfill_macro_data.py             # Full-history backfill (CN+US+Gold)
uv run python scripts/backfill_macro_data.py --market cn
uv run python scripts/backfill_macro_data.py --market gold
uv run python scripts/preview_p4_risk.py                 # Render P4 risk cards from stored data (no Claude/email)

# Tests
uv run pytest tests/                                # all tests
uv run pytest tests/test_data_layer.py -v           # data layer (BaseData/CNData/USData)
uv run pytest tests/test_provider_contract.py -v    # provider return-shape contracts
uv run pytest tests/test_risk_*.py -v               # P4 risk model (config/base-indicator/render/smoke)
uv run pytest tests/test_pipeline_critical.py -v    # critical-path (Claude fallback / send resilience / cron)
uv run pytest tests/test_holdings.py -v             # per-recipient holdings pipeline

# Docker
docker compose up --build                # Local: build scheduler from source
docker compose -f docker-compose.prod.yml up -d  # Prod: pull GHCR image
```

`--market {us,cn,all}` is accepted but **deprecated** — the report is always a merged US+CN single email regardless.

## Configuration

- `config.json` (gitignored) — `markets` (cron schedules), `email_service` (SMTP), `recipients[]`. Copy from `config.example.json`.
- **Schedule:** the scheduler honors the FIRST cron entry of the FIRST enabled market (us preferred). Since the macro pipeline always merges US+CN, keep one schedule entry per market — only the first enabled market's cron actually triggers runs.
- `recipients[]` shape: `{email, name, active, language, holdings?}`. Optional `holdings: [{symbol, market, type}]` (market∈{us,cn}, type∈{stock,etf,fund}; fund=CN 场外基金) triggers a separate per-recipient **holdings-analysis email** (distinct from the macro email). P1 market/type constraints enforced in `_validate_holdings` (`run.py`): **US supports `type=stock` only**; **`fund` is CN-only**. No web/auth fields.
- `.env` (gitignored) — `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` (see `core/llm.py:default_model()` — env value used as-is unless it carries a `[1m]` suffix, which is stripped/ignored because Claude Code's runtime leaks IDs like `glm-5.2[1m]` that compatible endpoints reject; hardcoded fallback is `claude-sonnet-4-5-20250929`, since `claude-sonnet-4-6` is **not** recognized by GLM-style Anthropic-compatible endpoints), `SMTP_PASSWORD`, and news keys (`FINNHUB_KEY`, `ALPHAVANTAGE_KEY`, `TAVILY_KEY`).
- `ANTHROPIC_AUTH_TOKEN` auto-aliases to `ANTHROPIC_API_KEY`.
- macOS system proxy auto-detected for yfinance; NO_PROXY set for akshare (eastmoney) domains.

## Architecture

### Email Pipeline (the only channel)

**Entry point:** `run.py` — `_run_macro_report(args)` builds ONE merged US+CN report.

Pipeline: `load config` → refresh data (US+CN `provider.refresh()` + `GoldData.update_incremental()`, all resilient — fall back to stored latest on failure) → fetch US macro (`USMarketProvider`) + CN macro (`CNMarketProvider`) + news → **compute P4 risk scores** (us/cn/gold via `RiskModel`, wrapped in `_safe_risk_score`) → Claude ①⑥ (`generate_macro_brief`, risk scores injected into context) → **research views** (Tavily `fetch_research_views` + Claude `generate_research_views`) → `render_section` (US + CN, each with `risk_html=`) + `render_gold_section` → `render_template` → `send_report` (one email). On `--dry-run`, prints JSON instead of sending.

Key `run.py` functions: `_run_macro_report` (macro pipeline), `_run_holdings_report` (per-recipient holdings pipeline), `generate_macro_brief` (Claude ①⑥) + `generate_research_views` (Claude sell-side synthesis), both via `core.llm.get_client`; `_serialize_macro_context` (feeds risk scores into Claude), `_safe_risk_score` (resilient `RiskModel` wrapper, returns `{}` on failure), `fetch_news`, `send_report`, `run_scheduler` / `_run_scheduled_macro` (single cron thread → macro then holdings).

### Data Layer (stateful, P1)

`investbrief/data/` — SQLite-backed macro data layer (ported from StockCycleRiskDetector). The single source of truth for index/macro time series; providers no longer fetch live.

- `base.py` — `BaseData`: schema (`cn_index_daily` / `us_index_daily` / `macro_data` / `sentiment_data` / `update_log`), `upsert_df` / `query` / `merge_sentiment_row` / `latest_bars(table, code, n)` / `latest_macro(indicator, country)` / `_retry_api`.
- `cn_data.py` — `CNData`: 5 A-share indices (`INDEX_CODES`) + LPR/M2/M1/社融/CN10Y/USDCNY (akshare + yfinance).
- `us_data.py` — `USData`: 11 symbols (`INDEX_SYMBOLS`: `^GSPC`/`^IXIC`/`^DJI`/`^VIX`/`^TNX`/`^FVX`/`^IRX`/`HYG`/`CL=F`/`DX-Y.NYB`/`GC=F`) + CPI/GDP.

DB at `data/macro_data.db` (gitignored; parent dir auto-created by `BaseData.conn`). Flow: provider `refresh()` → `data.update_incremental()` (per-method try/except, resilient), then `get_*` read latest bars/values. **Refresh failure → fall back to stored latest** (pipeline never blocks on one API; this is a resilience gain over the pre-P1 live-fetch path). First deploy: `scripts/backfill_macro_data.py`; daily补数: `uv run run.py --update`. Constants in `investbrief/config.py` (`DB_PATH`, `API_RETRY_*`, `US_GDP_BASE_*`).

### Risk Model (P4)

`investbrief/risk/` — market-cycle risk scoring (ported from StockCycleRiskDetector; that project's core). Produces a 0-100 risk score per market (us/cn/gold) from five weighted dimensions, with a state label and recommended action. **Tracking signal, not a prediction** — surfaced to Claude as context, never as a standalone buy/sell rule.

- `models.py` — `RiskModel(data_source)`: aggregates the six indicators; `calculate_score(market, date=None)` → `{total_score, state, crash_prob, expected_return, action, dimensions, indicators}`. Gold uses `GoldIndicator` alone; cn/us use valuation+technical+liquidity+sentiment+macro.
- `config.py` — `FIVE_DIMENSIONS` (weights), `COMMON_INDICATORS`/`CN_INDICATORS`/`US_INDICATORS`/`GOLD_INDICATORS` (combined into `*_ALL_INDICATORS`), `MARKET_STATE_MAP` (score→state), `BACKTEST_BUY_THRESHOLD=20` / `SELL_THRESHOLD=70`.
- `indicators/` — `base.py` (`BaseIndicator` ABC) + `valuation.py`/`technical.py`/`liquidity.py`/`sentiment.py`/`macro.py`/`gold.py`. Each reads series from the P1 data layer.
- `calc_utils.py` — `percentile_rank` and z-score helpers.
- `render.py` — `render_risk_card(score_data)` (US/CN card, injected into `MarketProvider.render_section` via `risk_html=`) + `render_gold_section(score_data)` (appended to `market_section_html`).

In the pipeline (`run.py`): `_safe_risk_score` wraps `calculate_score` (returns `{}` on failure → empty card, pipeline never blocks); scores are also serialized into the Claude context via `_serialize_macro_context` so ①⑥ can reference them. Preview without email: `scripts/preview_p4_risk.py`. Tests: `tests/test_risk_*.py` (config/base-indicator/render/smoke).

### Research views (sell-side commentary)

`investbrief/research/views.py` — `fetch_research_views()`: Tavily search over the last 7 days restricted to a **whitelist of reputable outlets** (Reuters/Bloomberg/CNBC/FT/WSJ/MarketWatch/Barron's; CN: sina/wallstreetcn/caixin/yicai; KR: koreaherald/koreatimes). Firm attribution is **title-based** (a firm is tagged only if it appears in the article *title*, never just the body — filters out roundup pages); items are tagged by market (美股 / A股·中国 / 全球其他). Returns structured items that `run.py:generate_research_views` synthesizes into the `🏦 卖方机构观点` section (Claude, `RESEARCH_VIEWS_PROMPT`). CN brokers (中信/华泰/申万) are intentionally out of scope — their views aren't in any free feed (verified). Tests: `tests/test_research_views.py`.

### Providers

`investbrief/core/provider.py` — `MarketProvider` ABC: `get_indices`, `get_monetary_policy`, `get_asset_performance`, `fetch_all`, `render_section`.

| Package | Module | Role |
|---------|--------|------|
| `core/` | `provider.py` | `MarketProvider` ABC (macro methods) |
| `core/` | `llm.py` | `get_client()` cached Anthropic client + `default_model()` |
| `core/` | `mailer.py` | `EmailSender` — SMTP with retry |
| `data/` | `base.py`/`cn_data.py`/`us_data.py`/`gold_data.py` | **Stateful SQLite data layer** (P1) — providers read index/macro series from here; `GoldData` adds gold price (akshare SGE) + US M2/CPI (FRED) with hardcoded 1980-2024 historical baselines; see Data Layer above |
| `us/` | `provider.py` | `USMarketProvider` — yfinance macro (indices, yields, gold) |
| `us/` | `clients.py` | `YFinanceClient` + Finnhub/Alpha Vantage/Tavily clients |
| `us/` | `news.py` | `DataProvider` — unified news with fallback and scoring |
| `us/` | `calendar.py` | US economic calendar (FOMC/CPI/NFP/PCE) via yfinance + rules |
| `cn/` | `provider.py` | `CNMarketProvider` — akshare macro (indices, LPR/M2/社融/国债, USDCNY) |
| `cn/` | `client.py` | `AKShareClient` — wraps akshare (macro monetary, ETF, index valuation) |
| `cn/` | `news.py` | A-share news via AKShare |
| `cn/` | `calendar.py` | A-share economic calendar (LPR/PMI/CPI/PPI/M2) |
| `etf/` | — | ETF analysis package (analyzer/engine/indicators/rules.json); reused by `holdings/` for CN ETF |
| `risk/` | `models.py`/`config.py`/`indicators/`/`calc_utils.py`/`render.py` | **Market-cycle risk model** (P4) — `RiskModel.calculate_score` for us/cn/gold; 5 weighted dimensions; renders risk card + gold section; see Risk Model above |
| `research/` | `views.py` | **Sell-side views aggregator** — Tavily search of whitelisted outlets (last 7d), title-based firm attribution, market-tagged; synthesized by `generate_research_views`; see Research views above |
| `holdings/` | `analyzer.py`/`brief.py`/`renderer.py` | **Holdings email pipeline** — per-recipient analysis (stock/etf/fund) by market/type; reuses `etf/` + clients |
| `report.py` | — | Template-rendering library: `load_template` / `render_template` / `render_holdings_template` / `translate_html` (multi-language via Claude) |

### Macro data sources (verified)

- US rates: yfinance `^TNX`(10Y), `^FVX`(5Y), `^IRX`(13W); broad assets: `^GSPC`/`^IXIC`/`^DJI`/`^VIX`/`CL=F`/`DX-Y.NYB`/`GC=F`(gold). Fed funds target = static constant (update on FOMC).
- CN monetary: akshare `macro_china_lpr` (LPR1Y/5Y), `macro_china_money_supply` (M2/M1 YoY), `macro_china_shrzgm` (社融), `bond_china_yield` (CN 10Y, filter 中债国债收益率曲线); FX: yfinance `USDCNY=X`.
- **akshare frames are inconsistently ordered** — always sort by date/month column descending for latest, never rely on position.
- CN-US yield spread is inferred by Claude from US 10Y and CN 10Y (both passed through separately by the pipeline; no explicit subtraction is computed).

### Report structure (email)

`templates/email_base.html`: header (宏观日报 title) → ① 核心观点 (`.summary-box`, Claude) → `{{market_sections}}` (US section + CN section, each: 大类资产 / 货币政策 / 经济日历 + a P4 risk card) + gold section → 🏦 卖方机构观点 (`{{research_views}}`, Claude) → ⑥ 风险提示与下周关注 → news → footer. `report.render_template` replaces `{{macro_summary}}`/`{{risk_outlook}}`/`{{market_sections}}`/`{{research_views}}`/`{{global_news}}` etc. (report_data keys `market_section_html` / `news` map to the `{{market_sections}}` / `{{global_news}}` placeholders).

The **holdings email** (`templates/email_holdings.html`, separate from macro) renders per-recipient: header → `{{holdings_summary}}` (Claude 组合研判) → `{{holdings_sections}}` (one card per holding). Each card shows available dimensions by `type`: price/NAV, rating distribution + **multi-period trend** (本期 vs 上期, pct-point) + analyst actions + price target (US only), fundamentals (PE/ROE/returns), technicals (MA/RSI/MACD, via `etf/indicators.py`), flow (CN only), news. Missing dimensions degrade gracefully. `report.render_holdings_template` replaces the placeholders.

## Key Conventions

- Pipeline is resilient: API failures log warnings and continue with empty data / fallback. Claude failure → ①⑥ use placeholder strings, report still sends.
- Color scheme: Chinese convention — red = up, green = down (`#e74c3c` / `#27ae60`).
- Adding a new macro section: add a `get_*` method to `MarketProvider` ABC + US/CN implementations + a `_render_*` helper + call in `render_section` + include in `_serialize_macro_context` for Claude.
- Anthropic client: always via `investbrief.core.llm.get_client()` (don't construct `anthropic.Anthropic(...)` inline).
- Previews saved to `reports/preview_macro.html` (and `reports/preview_holdings.html` for the holdings pipeline) after each non-dry-run.
- Model configurable via `ANTHROPIC_DEFAULT_SONNET_MODEL` (see Configuration for the `[1m]` filtering quirk).

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

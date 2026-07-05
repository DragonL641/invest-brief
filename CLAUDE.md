# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a macro-economic market report app that generates a daily **US+CN dual-view** briefing and sends it via email (SMTP). Pure backend (no web layer). Output is **Chinese-only** (Korean/translation support was removed).

- Each trading day: fetch US+CN macro data (rates, monetary aggregates, broad assets, economic calendar, news) → Claude generates a core-view summary + risk outlook → render a merged dual-view HTML report → send one email to all active recipients.
- Data sources: yfinance (US), akshare (CN), external news APIs, Claude for synthesis.
- Two email types: the **macro email** (daily, broadcast to all active recipients) and the optional **holdings email** (per-recipient, sent only to recipients who configure a `holdings` list). The `investbrief/holdings/etf/` sub-package is reused by the holdings pipeline for CN ETF analysis.

## Commands

```bash
# Email pipeline (the only entry point)
uv run run.py --dry-run                  # Build merged macro report, output JSON to stdout, no email
uv run run.py --dry-run --skip-summary   # Skip Claude ①⑥ (faster, structure-only)
uv run run.py --dry-run --only holdings  # Build per-recipient holdings email (needs recipients[].holdings)
uv run run.py --now                      # Run once: build + send email
uv run run.py --update                   # Refresh macro data into SQLite only, no render/email
uv run run.py                            # Scheduler mode (cron-based; runs macro then holdings)
# --only {macro,holdings} limits a single run to one pipeline (default: both)

# Data backfill (first deploy only, ~10-30 min)
uv run python scripts/backfill_macro_data.py             # Full-history backfill (CN+US+Gold)
uv run python scripts/backfill_macro_data.py --market cn
uv run python scripts/backfill_macro_data.py --market gold
uv run python scripts/preview_p4_risk.py                 # Render P4 risk cards from stored data (no Claude/email)

# Tests
uv run pytest tests/                                # all tests
uv run pytest tests/ -q -m "not network"            # CI invocation: exclude real-API tests
uv run pytest tests/test_data_layer.py -v           # data layer (BaseData/CNData/USData)
uv run pytest tests/test_provider_contract.py -v    # provider return-shape contracts
uv run pytest tests/test_risk_*.py -v               # P4 risk model (config/base-indicator/render/smoke)
uv run pytest tests/test_regime_engine.py -v        # economic-quadrant regime engine
uv run pytest tests/test_strategy_loader.py -v      # strategy YAML loader
uv run pytest tests/test_pipeline_critical.py -v    # critical-path (Claude fallback / send resilience / cron)
uv run pytest tests/test_holdings.py -v             # per-recipient holdings pipeline

# Lint (CI selects fatal errors only — E9/F7/F82/F811; no style enforcement)
uv run ruff check --select E9,F7,F82,F811 .

# Docker
docker compose up --build                # Local: build scheduler from source
docker compose -f docker-compose.prod.yml up -d  # Prod: pull GHCR image
```

`--market {us,cn,all}` is accepted but **deprecated** — the report is always a merged US+CN single email regardless. The `network` pytest marker flags tests that hit real external APIs; they are excluded from the PR gate (run locally with no marker filter to execute them).

## Configuration

- `config.json` (gitignored) — `markets` (cron schedules), `email_service` (SMTP), `recipients[]`. Copy from `config.example.json`.
- **Schedule:** the scheduler honors the FIRST cron entry of the FIRST enabled market (us preferred). Since the macro pipeline always merges US+CN, keep one schedule entry per market — only the first enabled market's cron actually triggers runs.
- `recipients[]` shape: `{email, name, active, language, holdings?}`. `language` is accepted but currently ignored (Chinese-only output; kept for call-site compat). Optional `holdings: [{symbol, market, type}]` (market∈{us,cn}, type∈{stock,etf,fund}; fund=CN 场外基金) triggers a separate per-recipient **holdings-analysis email** (distinct from the macro email). P1 market/type constraints enforced in `_validate_holdings` (`run.py`): **US supports `type=stock` only**; **`fund` is CN-only**. No web/auth fields.
- `.env` (gitignored) — `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` (see `core/llm.py:default_model()` — env value used as-is unless it carries a `[1m]` suffix, which is stripped/ignored because Claude Code's runtime leaks IDs like `glm-5.2[1m]` that compatible endpoints reject; hardcoded fallback is `claude-sonnet-4-5-20250929`, since `claude-sonnet-4-6` is **not** recognized by GLM-style Anthropic-compatible endpoints), `SMTP_PASSWORD`, and news keys (`FINNHUB_KEY`, `ALPHAVANTAGE_KEY`, `TAVILY_KEY`).
- `ANTHROPIC_AUTH_TOKEN` auto-aliases to `ANTHROPIC_API_KEY`.
- macOS system proxy auto-detected for yfinance; NO_PROXY set for akshare (eastmoney) domains.

## Architecture

**Domain-layer layout (refactor/modular-split):** packages are split by business domain, not tech layer. Dependency direction is strictly one-way — `run.py → pipelines → {market, holdings, risk, regime, mail} → {data, datasources} → core`. `strategies/*.yaml` are static config, loaded read-only by `risk/` and `holdings/etf/` through `core/strategy_loader.py` (not a domain layer). Domains have **ZERO 横向 dependencies** on each other (e.g., `market/` does not import `holdings/` or `mail/`; they collaborate only via `pipelines/`). Future changes must preserve this invariant.

**Extension seams (no plugin framework, just dict registry + DI):**
- New market → implement `MarketProvider` subclass in `market/<mkt>/` + register one line in `market/__init__.py:MARKET_PROVIDERS`.
- New report type → add a `pipelines/<name>.py` + dispatch entry in `run.py:run_once`.

### Email Pipeline (the only channel)

**Entry point:** `run.py` — a ~150-line CLI shell: `argparse` + proxy/env bootstrap + `main()`. `main()` parses args and dispatches to `run_once(args)`, which fans out to the right pipeline (`--only {macro,holdings}`, default: both). All orchestration lives in `pipelines/`.

**Macro pipeline** (`pipelines/macro.py:run_macro_report`): `load config` → refresh data (US+CN `provider.refresh()` via `market.create_provider` + `GoldData.update_incremental()`, all resilient — fall back to stored latest on failure; refresh is DB-First fast-path, skipping when today's bars already exist) → fetch US macro (`USMarketProvider`) + CN macro (`CNMarketProvider`) + news (`fetch_news`) → **compute P4 risk scores** (us/cn/gold via `RiskModel`, wrapped in `_safe_risk_score`) → **judge economic regime** (us/cn via `RegimeEngine`, wrapped in `_safe_regime_judge`) → Claude ①⑥ (`market.macro_brief.generate_macro_brief` — one JSON call returning `(summary, risk)`, risk scores + regime data injected via `serialize_macro_context`) → **research views** (`market.research.fetch_research_views` + `generate_research_views`) → `MarketProvider.render_section` (US + CN, each with `risk_html=` and `regime_html=`) + `render_gold_section` → `mail.render.render_template` → `pipelines._send.send_report` (one email). On `--dry-run`, prints JSON instead of sending.

**Holdings pipeline** (`pipelines/holdings.py:run_holdings_report`): per-recipient analysis (stock/etf/fund) by market/type, reuses `holdings/etf/` for CN ETF. Holdings are deduplicated across recipients so each unique symbol is analyzed once. Sends via `EmailSender.send_bulk` (one SMTP connection for all recipients). Distinct template, distinct send loop.

**Scheduler** (`pipelines/scheduler.py`): `run_scheduler` (single cron thread) → `_run_scheduled_macro` → runs macro then holdings. `first_enabled_cron` picks the cron; `request_shutdown` handles signals.

Key symbols (all Claude calls go through `core.llm.call_claude`; client via `core.llm.get_client`): `pipelines.macro.run_macro_report` / `fetch_news` / `_safe_risk_score` / `_safe_regime_judge`; `pipelines.holdings.run_holdings_report`; `pipelines.scheduler.run_scheduler` / `first_enabled_cron` / `_run_scheduled_macro`; `pipelines._send.send_report`; `market.macro_brief.generate_macro_brief` / `serialize_macro_context` / `MACRO_BRIEF_PROMPT`; `market.research.fetch_research_views` / `generate_research_views` / `RESEARCH_VIEWS_PROMPT`.

### LLM reliability layer

`investbrief/core/` centralizes every Claude interaction so resilience logic lives in one place. **Always call Claude through `core.llm.call_claude`** — never construct `client.messages.create` inline.

- `llm.py:call_claude(messages, *, system, max_tokens, temperature, max_retries)` — unified wrapper: classifies the exception via `classify_anthropic_error`, retries only retryable classes (network/timeout/rate-limit/5xx) with exponential backoff (base 1s × 2^attempt + jitter, cap 30s), returns stripped text on success or **`None` on failure**. Callers handle `None` with their own fallback string.
- `llm_errors.py:classify_anthropic_error(exc) → ClassifiedError(code, retryable)` — uses BOTH the SDK exception class name AND error-message text sniffing, because GLM-style Anthropic-compatible endpoints emit error bodies that don't map to the SDK's exception classes. `unknown` defaults to NOT retryable.
- `llm_json.py:extract_json(text) → dict` — tolerant JSON extraction for `macro_brief`'s `{summary, risk}` output: strip markdown fence → `json.loads` → `raw_decode` (tolerate trailing prose) → `json_repair` (tolerate Python-style bools/None, single quotes, trailing commas). Raises `ValueError` if all stages fail.
- `logging.py:setup_logging` — centralized format + third-party noise suppression; invoked from `run.py`.
- `textfmt.py:md_inline` — Markdown → inline HTML (bold/italic/heading/list), produces NO block elements (no `<h2>`/`<ul>`) to avoid CSS font inheritance in email; shared by `holdings/` and `mail/`.

### Strategy files (externalized YAML)

`investbrief/strategies/` holds tunable strategy config as YAML, decoupled from code so weights/thresholds/rules can change without touching Python. Loaded via `core/strategy_loader.py:load_strategy(name)` — `lru_cache`d (static after startup; call `load_strategy.cache_clear()` in tests that mutate) + schema-validated + friendly errors.

- `risk_indicators.yaml` — P4 risk indicator definitions (`common`/`cn`/`us`/`gold` groups), consumed by `risk/config.py` (each indicator: `weight`, `category`, `thresholds`/`low_thresholds` per market, `invert`, `scale`, `unit`, `explain`). Replaces formerly-hardcoded indicator dicts.
- `etf_rules.yaml` — ETF analysis `rules[]`, consumed by `holdings/etf/engine.py`. Each rule: `id`, `enabled` (default true; toggle without deleting), `dimension`, `name`, `description`, `condition` (Python expr evaluated against a flattened indicators dict via `eval` with `_SAFE_BUILTINS`, no `__builtins__`), `signal` (bullish/bearish/neutral), `weight`. Replaces the deleted `holdings/etf/rules.json`.

### Risk Model (P4)

`investbrief/risk/` — market-cycle risk scoring (ported from StockCycleRiskDetector; that project's core). Produces a 0-100 risk score per market (us/cn/gold) from five weighted dimensions, with a state label and recommended action. **Tracking signal, not a prediction** — surfaced to Claude as context, never as a standalone buy/sell rule. **Indicator definitions (weights / thresholds / invert / scale / explain) are externalized to `strategies/risk_indicators.yaml`** — change thresholds by editing the YAML, no Python changes; loaded at runtime by `core/strategy_loader.py:load_strategy` (see Strategy files above).

- `models.py` — `RiskModel(data_source)`: aggregates the six indicators; `calculate_score(market, date=None)` → `{total_score, state, risk_level, crash_prob, expected_return, action, dimensions, indicators}`. Gold uses `GoldIndicator` alone; cn/us use valuation+technical+liquidity+sentiment+macro.
- `config.py` — `MARKET_STATE_MAP` (score→state, 人读, used for report rendering) **and** `RISK_LEVEL_MAP` + `score_to_risk_level()` (score→`low`/`moderate`/`high`/`extreme`, used for decision branches / Claude prompt / future alert thresholds — two separate vocabularies kept apart on purpose). `FIVE_DIMENSIONS` (radar weights), `*_ALL_INDICATORS` (loaded from `strategies/risk_indicators.yaml` via `load_strategy`), `BACKTEST_BUY_THRESHOLD=20` / `SELL_THRESHOLD=70`.
- `indicators/` — `base.py` (`BaseIndicator` ABC) + `valuation.py`/`technical.py`/`liquidity.py`/`sentiment.py`/`macro.py`/`gold.py`. Each reads series from the P1 data layer.
- `calc_utils.py` — `percentile_rank` and z-score helpers.
- `render.py` — `render_risk_card(score_data)` (US/CN card, injected into `MarketProvider.render_section` via `risk_html=`) + `render_gold_section(score_data)` (appended to `market_section_html`).

In the pipeline: `_safe_risk_score` wraps `calculate_score` (returns `{}` on failure → empty card, pipeline never blocks); scores are also serialized into the Claude context via `serialize_macro_context`. Preview without email: `scripts/preview_p4_risk.py`. Tests: `tests/test_risk_*.py`.

### Regime model (economic quadrant)

`investbrief/regime/` — a **second opinionated signal** alongside the risk model: the Browne permanent-portfolio quadrant from growth×inflation (繁荣/通胀/通缩/滞胀/中性). Same "tracking, not predicting" stance as risk.

- `engine.py` — `RegimeEngine(data_source).judge(market)` → `{quadrant, confidence, growth_axis, inflation_axis, indicators, market}`. GDP absolute values → YoY (`_yoy_from_absolute`); direction via trend voting (`_direction_vote`, needs ≥`DIRECTION_VOTE_MIN_AGREEING` agreeing periods); `_classify` maps growth×inflation to a quadrant (inflation-up also requires `CPI > INFLATION_UP_THRESHOLD`). Three de-noising layers: trend vote, CPI level threshold, and **switch confirmation** (`SWITCH_CONFIRMATION_RUNS=2` — re-judges on the lookback window and downgrades to 中性 if the quadrant changed, avoiding single-period noise). Module-level `_judge_from_series` etc. are pure functions with no DB access (unit-tested directly).
- `config.py` — `QUADRANTS` (占优资产 per quadrant for card annotation), thresholds, GDP/CPI `indicator` keys aligned with the data layer.
- `render.py` — `render_regime_card(data)`.

In the macro pipeline: `_safe_regime_judge` (returns `{}` on failure → empty card); the card is passed as `regime_html=` to `MarketProvider.render_section` (same data-only injection pattern as `risk_html=`), and `regime_data=` is serialized into `generate_macro_brief`. Reads only existing CPI (YoY) + GDP (absolute) series from `macro_data` — no new data sources. Tests: `tests/test_regime_engine.py` / `test_regime_render.py`.

> **Two different "regime" concepts — do not confuse.** This `regime/` package is the *macro economic quadrant*. Separately, `holdings/regime_prompts.py` + `holdings/etf/indicators.py:_calc_regime` produce a *per-holding technical regime* (`trending_up`/`trending_down`/`volatile`/`sideways`) that is injected into the holdings Claude prompt as a hint. Different inputs, different consumers, different module.

### Research views (sell-side commentary)

`investbrief/market/research.py` — `fetch_research_views()`: Tavily search over the last 7 days restricted to a **whitelist of reputable outlets** (Reuters/Bloomberg/CNBC/FT/WSJ/MarketWatch/Barron's; CN: sina/wallstreetcn/caixin/yicai). Firm attribution is **title-based** (a firm is tagged only if it appears in the article *title*, never just the body — filters out roundup pages); items are tagged by market (美股 / A股·中国 / 全球其他). The same module also hosts `generate_research_views` (Claude synthesis via `call_claude`, `RESEARCH_VIEWS_PROMPT`) and `serialize_research_views`, invoked from `pipelines/macro.py` to render the `🏦 卖方机构观点` section. CN brokers (中信/华泰/申万) are intentionally out of scope — their views aren't in any free feed (verified). Tests: `tests/test_research_views.py`.

### Data Layer (stateful, P1)

`investbrief/data/` — SQLite-backed macro data layer (ported from StockCycleRiskDetector). The single source of truth for index/macro time series; providers read from here, they no longer fetch live per-call.

- `base.py` — `BaseData`: schema (`cn_index_daily` / `us_index_daily` / `macro_data` / `sentiment_data` / `update_log`), `upsert_df` / `query` / `merge_sentiment_row` / `latest_bars(table, code, n)` / `latest_macro(indicator, country)` / `_retry_api`, plus a **DB-First fast-path** helper so `refresh()` skips fetching when today's bars already exist.
- `cn_data.py` — `CNData`: 5 A-share indices (`INDEX_CODES`) + LPR/M2/M1/社融/CN10Y/USDCNY (akshare + yfinance).
- `us_data.py` — `USData`: 11 symbols (`INDEX_SYMBOLS`: `^GSPC`/`^IXIC`/`^DJI`/`^VIX`/`^TNX`/`^FVX`/`^IRX`/`HYG`/`CL=F`/`DX-Y.NYB`/`GC=F`) + CPI/GDP.
- `gold_data.py` — `GoldData`: gold price (akshare SGE) + US M2/CPI (FRED) with hardcoded 1980-2024 historical baselines.

DB at `data/macro_data.db` (gitignored; parent dir auto-created by `BaseData.conn`). Flow: provider `refresh()` → `data.update_incremental()` (per-method try/except, resilient), then `get_*` read latest bars/values. **Refresh failure → fall back to stored latest** (pipeline never blocks on one API). First deploy: `scripts/backfill_macro_data.py`; daily补数: `uv run run.py --update`. Constants live in `core/config.py` (`DB_PATH`, `API_RETRY_*`, `US_GDP_BASE_*`) — the old top-level `investbrief/config.py` is gone.

**eastmoney throttling (operational):** akshare hits eastmoney's data center, which rate-limits aggressively. Mitigations live in `datasources/akshare.py`: UA/Referer injection via a `Session.request` patch, `_with_retry` with random backoff (longer on the last retry), **negative caching** for `spot_em` and full-universe fetches (a failed full sweep is remembered, not re-attempted), and `get_stock_quote` via the bid_ask endpoint with name lookup. `run.py` force-bypasses the system proxy for eastmoney domains (NO_PROXY) — proxy SSL hijist breaks CN quotes/history/flow. `holdings/analyzer` concurrency is capped at 2 to ease throttling.

### Providers

`investbrief/market/base.py` — `MarketProvider` ABC: `get_indices`, `get_monetary_policy`, `get_asset_performance`, `fetch_all`, `render_section`. `render_section` accepts opaque `risk_html=` and `regime_html=` kwargs (cross-domain injection — see Conventions). Concrete providers are registered in `market/__init__.py:MARKET_PROVIDERS` and instantiated via `create_provider(market)`.

| Package | Module | Role |
|---------|--------|------|
| `core/` | `llm.py` | `get_client()` cached client + `default_model()` + **`call_claude()` unified wrapper** |
| `core/` | `llm_errors.py` / `llm_json.py` | `classify_anthropic_error` / `extract_json` (json-repair fallback) |
| `core/` | `logging.py` / `textfmt.py` | centralized `setup_logging` / `md_inline` (Markdown→inline HTML) |
| `core/` | `strategy_loader.py` | `load_strategy(name)` — lru_cached YAML loader for `strategies/` |
| `core/` | `config.py` | `load_config` / `validate_config` / `validate_holdings` + constants (`DB_PATH`, `API_RETRY_*`, `US_GDP_BASE_*`, `REPORTS_DIR`) — formerly top-level `investbrief/config.py` |
| `strategies/` | `risk_indicators.yaml` / `etf_rules.yaml` | Externalized P4 indicator config / ETF analysis rules (YAML) |
| `data/` | `base.py` / `cn_data.py` / `us_data.py` / `gold_data.py` | **Stateful SQLite data layer** (P1) — providers read index/macro series from here; DB-First refresh fast-path; see Data Layer above |
| `datasources/` | `yfinance.py` / `akshare.py` / `finnhub.py` / `alphavantage.py` / `tavily.py` / `_common.py` | **API adapters** — thin wrappers over external APIs; `akshare.py` carries eastmoney throttling mitigations (UA/Referer, negative cache, backoff, `get_stock_quote`) |
| `market/` | `base.py` | `MarketProvider` ABC (macro methods + `render_section` with `risk_html=`/`regime_html=`) |
| `market/` | `__init__.py` | `MARKET_PROVIDERS` registry (`{"us": USMarketProvider, "cn": CNMarketProvider}`) + `create_provider(market)` factory |
| `market/` | `macro_brief.py` | `MACRO_BRIEF_PROMPT` + `serialize_macro_context` + `generate_macro_brief` (Claude ①⑥, one JSON call → `(summary, risk)` tuple via `call_claude`+`extract_json`) |
| `market/` | `research.py` | `fetch_research_views` (Tavily) + `RESEARCH_VIEWS_PROMPT` + `serialize_research_views` + `generate_research_views`; see Research views above |
| `market/us/` | `provider.py` / `calendar.py` / `news.py` | `USMarketProvider` — yfinance macro (indices, yields, gold); US economic calendar (FOMC/CPI/NFP/PCE); unified news with fallback + scoring |
| `market/cn/` | `provider.py` / `calendar.py` / `news.py` | `CNMarketProvider` — akshare macro (indices, LPR/M2/社融/国债, USDCNY); A-share calendar (LPR/PMI/CPI/PPI/M2); A-share news |
| `risk/` | `models.py` / `config.py` / `calc_utils.py` / `render.py` / `indicators/` | **Market-cycle risk model** (P4) — `RiskModel.calculate_score` for us/cn/gold; 5 weighted dimensions; `state` (人读) + `risk_level` (low/moderate/high/extreme); indicators loaded from `strategies/risk_indicators.yaml`; see Risk Model above |
| `regime/` | `engine.py` / `config.py` / `render.py` | **Economic-quadrant regime** — `RegimeEngine.judge` (Browne growth×通胀); reads GDP+CPI from `macro_data`; see Regime model above |
| `holdings/` | `analyzer.py` / `brief.py` / `renderer.py` / `regime_prompts.py` + `etf/{analyzer,engine,indicators}` | **Holdings email pipeline** — per-recipient analysis (stock/etf/fund) by market/type; `_with_ai`/`generate_stock_conclusion` adds Claude single-stock brief (`_fallback_stock_conclusion` rule-based on failure); `_extract_technicals` produces 18 technical fields; `regime_prompts.py` injects the **per-holding technical regime** hint; the former `etf/rules.json` is externalized to `strategies/etf_rules.yaml` |
| `mail/` | `sender.py` | `EmailSender` — SMTP with retry; `send` + `send_bulk(messages)→(sent, failed)` (one connection for N recipients) |
| `mail/` | `render.py` | **Jinja2** template-rendering library: `load_template` / `render_template` / `render_holdings_template`. Chinese-only; `autoescape=False` (vars are pre-rendered HTML fragments); `language` arg accepted but ignored. `translate_html` was deleted. Formerly top-level `report.py` |
| `mail/` | `templates/{email_base,email_holdings}.j2` | Jinja2 templates (`.j2`) |
| `pipelines/` | `macro.py` / `holdings.py` / `scheduler.py` / `_send.py` | **Pipeline orchestration** — `run_macro_report` + `fetch_news` + `_safe_risk_score` + `_safe_regime_judge`; `run_holdings_report`; `run_scheduler` / `first_enabled_cron` / `_run_scheduled_macro`; `send_report` helper |

### Macro data sources (verified)

- US rates: yfinance `^TNX`(10Y), `^FVX`(5Y), `^IRX`(13W); broad assets: `^GSPC`/`^IXIC`/`^DJI`/`^VIX`/`CL=F`/`DX-Y.NYB`/`GC=F`(gold). Fed funds target = static constant (update on FOMC).
- CN monetary: akshare `macro_china_lpr` (LPR1Y/5Y), `macro_china_money_supply` (M2/M1 YoY), `macro_china_shrzgm` (社融), `bond_china_yield` (CN 10Y, filter 中债国债收益率曲线); FX: yfinance `USDCNY=X`.
- **akshare frames are inconsistently ordered** — always sort by date/month column descending for latest, never rely on position.
- CN-US yield spread is inferred by Claude from US 10Y and CN 10Y (both passed through separately by the pipeline; no explicit subtraction is computed).

### Report structure (email)

`mail/templates/email_base.j2`: header (宏观日报 title) → ① 核心观点 (`.summary-box`, Claude) → `{{market_sections}}` (US section + CN section, each: 大类资产 / 货币政策 / 经济日历 + a P4 risk card + an economic-regime card) + gold section → 🏦 卖方机构观点 (`{{research_views}}`, Claude) → ⑥ 风险提示与下周关注 → news → footer. `mail.render.render_template` passes `report_data` into the Jinja2 environment (keys `macro_summary` / `risk_outlook` / `market_section_html` / `research_views` / `news` map to the template placeholders).

The **holdings email** (`mail/templates/email_holdings.j2`, separate from macro) renders per-recipient: header → `{{holdings_summary}}` (Claude 组合研判) → `{{holdings_sections}}` (one card per holding). Each card shows available dimensions by `type`: price/NAV, rating distribution + **multi-period trend** (本期 vs 上期, pct-point) + analyst actions + price target (US only), fundamentals (PE/ROE/returns), technicals (MA/RSI/MACD + 18-field `_extract_technicals`, via `holdings/etf/indicators.py`), flow (CN only), news, and an AI single-stock conclusion (`ai_conclusion`). Missing dimensions degrade gracefully. `mail.render.render_holdings_template` passes the data dict into Jinja2.

## Key Conventions

- Pipeline is resilient: API failures log warnings and continue with empty data / fallback. Claude failure (call_claude returns None) → ①⑥ use placeholder strings, report still sends.
- Color scheme: Chinese convention — red = up, green = down (`#e74c3c` / `#27ae60`).
- **Domain-layer invariant** — domains (`market/`, `holdings/`, `risk/`, `regime/`, `mail/`) must not import each other; they collaborate only through `pipelines/`. Lower layers (`data/`, `datasources/`) never reach up. Preserve this when adding code.
- **Cross-domain collaboration is data-only.** Cross-domain render injection is allowed *only* when the handoff is **data through `pipelines/`**, never an import. Two canonical instances: (1) `risk/render.py:render_risk_card` HTML → passed to `MarketProvider.render_section(..., risk_html=...)`; (2) `regime/render.py:render_regime_card` HTML → passed to `render_section(..., regime_html=...)`. `market/` never imports `risk/` or `regime/`; it only accepts opaque HTML strings. Follow this pattern for any future cross-domain render injection.
- **All Claude calls go through `core.llm.call_claude`** (error classification + backoff + None-on-failure). JSON-shaped responses go through `core.llm_json.extract_json`. Do not call `client.messages.create` inline or hand-roll JSON parsing.
- **Tunable strategy config lives in `strategies/*.yaml`**, loaded via `core.strategy_loader.load_strategy` (lru_cached). Do not hardcode indicator weights/thresholds or ETF rule definitions in Python; edit the YAML.
- Adding a new macro section: add a `get_*` method to `MarketProvider` ABC in `market/base.py` + US/CN implementations in `market/us/` & `market/cn/` + a `_render_*` helper called from `render_section` + include the new field in `market.macro_brief.serialize_macro_context` so Claude sees it.
- Adding a new market: implement a `MarketProvider` subclass under `market/<mkt>/` + register one line in `market/__init__.py:MARKET_PROVIDERS`. No `run.py` core changes needed — `create_provider(market)` picks it up. (Data-layer and datasource support must obviously exist first.)
- Adding a new report type: add `pipelines/<name>.py` with a `run_<name>_report(args)` + dispatch entry in `run.py:run_once`.
- Anthropic client: always via `investbrief.core.llm.get_client()` (don't construct `anthropic.Anthropic(...)` inline).
- Previews saved to `reports/preview_macro.html` (and `reports/preview_holdings.html` for the holdings pipeline) after each non-dry-run.
- Model configurable via `ANTHROPIC_DEFAULT_SONNET_MODEL` (see Configuration for the `[1m]` filtering quirk).

## CI/CD

### PR Check (`.github/workflows/pr-check.yml`)
`pull_request` to main → `uv sync --frozen` (lockfile consistency) + `uv run ruff check --select E9,F7,F82,F811 .` (fatal errors only — `[tool.ruff]` rule set is intentionally empty, no style enforcement, avoids taste debates) + `uv run pytest tests/ -q -m "not network"` (real-API tests excluded via the `network` marker).

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

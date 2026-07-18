# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**invest-brief** — a macro-economic market report app focused on **A 股**(A-share), with a light **外围环境卡** for signals that move A 股 (美联储利率/美债10Y/标普500/USDCNY). Generates a daily briefing and sends it via email (SMTP). Pure backend (no web layer). Output is **Chinese-only** (Korean/translation support was removed).

- Each trading day: fetch CN macro data + 外围环境 + 黄金 (rates, monetary aggregates, broad assets, economic calendar, news) → Claude generates a core-view summary + risk outlook → render a merged HTML report → send one email to all active recipients.
- Data sources: **akshare only** (CN indices/monetary, 外围 environment, 黄金 SGE) + FRED (US M2/CPI for gold) + Tavily (news/research). **Zero yfinance dependency** (the former US pipeline and all US/yfinance code were removed in the cn-pivot refactor).
- Three email types: the **macro email** (daily, broadcast to all active recipients), the optional **holdings email** (per-recipient, sent only to recipients who configure a `holdings` list), and the optional **picks email** (daily A 股 selection, broadcast). The `investbrief/holdings/etf/` sub-package is reused by the holdings pipeline for CN ETF analysis.

## Commands

```bash
# Email pipeline (the only entry point)
uv run run.py --dry-run                  # Build macro report, output JSON to stdout, no email
uv run run.py --dry-run --skip-summary   # Skip Claude ①⑥ (faster, structure-only)
uv run run.py --dry-run --only holdings  # Build per-recipient holdings email (needs recipients[].holdings)
uv run run.py --dry-run --only picks     # Build A 股 selection email
uv run run.py --now                      # Run once: build + send email
uv run run.py --force                    # 跳过邮件日级缓存,强制重新生成 macro/picks/holdings
uv run run.py --update                   # Refresh macro data into SQLite only, no render/email
uv run run.py                            # Scheduler mode (cron-based; runs macro/holdings/picks)
# --only {macro,holdings,picks} limits a single run to one pipeline (default: all)

# Data backfill (first deploy only, ~10-30 min)
uv run python scripts/backfill_macro_data.py             # Full-history backfill (CN+Gold)
uv run python scripts/backfill_macro_data.py --market cn
uv run python scripts/backfill_macro_data.py --market gold
uv run python scripts/preview_p4_risk.py                 # Render P4 risk cards from stored data (no Claude/email)

# Tests
uv run pytest tests/                                # all tests
uv run pytest tests/ -q -m "not network"            # CI invocation: exclude real-API tests
uv run pytest tests/test_data_layer.py -v           # data layer (BaseData/CNData/GoldData)
uv run pytest tests/test_provider_contract.py -v    # provider return-shape contracts
uv run pytest tests/test_risk_*.py -v               # P4 risk model (config/base-indicator/render/smoke)
uv run pytest tests/test_regime_engine.py -v        # economic-quadrant regime engine
uv run pytest tests/test_strategy_loader.py -v      # strategy YAML loader
uv run pytest tests/test_pipeline_critical.py -v    # critical-path (Claude fallback / send resilience / cron)
uv run pytest tests/test_holdings.py -v             # per-recipient holdings pipeline

# Lint (CI: ruff select E9/F/UP — 致命错误 + pyflakes + pyupgrade;见 pyproject.toml)
uv run ruff check .

# Docker
docker compose up --build                # Local: build scheduler from source
docker compose -f docker-compose.prod.yml up -d  # Prod: pull GHCR image
```

`--market {cn,all}` is accepted but **deprecated and effectively a no-op** — cn-pivot 后报告恒为「A 股主 section + 外围环境卡 + 黄金」单一合并邮件,无 us macro section。`--market` 仅保留 CLI 兼容性(`us` 已不是有效值,`--market us` 会被 argparse 拒绝)。The `network` pytest marker flags tests that hit real external APIs; they are excluded from the PR gate (run locally with no marker filter to execute them).

## Configuration

- `config.json` (gitignored) — `markets` (cron schedules), `email_service` (SMTP), `recipients[]`. Copy from `config.example.json`.
- **Schedule:** the scheduler honors the FIRST cron entry of the FIRST enabled market. `first_enabled_cron`(`scheduler.py`)按 `for market in ("us", "cn")` **优先 us**(残留偏好);因 `config.example.json` 已设 `us.enabled=false`,实际落到 **cn 的 cron**。若保留 `us.enabled=true`,scheduler 会在 us 的 cron 时点触发(us 已无 provider,`macro.py` 显式过滤 `c != "us"`,报告仍是合并的 A 股邮件,不会独立跑 us section)。生产配置建议保持 `us.enabled=false`,让 cn 的 cron 成为唯一触发源。（缺失 `enabled` 字段现默认 `False` —— us 块缺失不再误启用为 us 优先调度。）
- **错峰(生产推荐):** scheduler 单 cron 串行 macro/holdings/picks 三 pipeline, macro refresh 独占 em 配额后 holdings/picks 易踩封禁。生产建议用**系统 cron 拆分多次 `--only`** 错峰(改 scheduler 不降 em 总量、只降峰值; 且 picks spot 已加跨 run 持久层兜底, 边际收益低, 故不动 scheduler): `30 10 * * 1-5 uv run run.py --only macro --now` / `45 10 * * 1-5 uv run run.py --only picks --now` / `50 10 * * 1-5 uv run run.py --only holdings --now`(macro 先跑独占 refresh; picks/holdings 错后分散 em 拉取)。scheduler 单 cron 仅作兜底。
- `recipients[]` shape: `{email, name, active, language, holdings?}`. `language` is accepted but currently ignored (Chinese-only output; kept for call-site compat). Optional `holdings: [{symbol, market, type}]` (**market∈{cn}**, type∈{stock,etf,fund}; fund=CN 场外基金) triggers a separate per-recipient **holdings-analysis email** (distinct from the macro email). P1 market/type constraints enforced in `validate_holdings` (`core/config.py`): `_VALID_HOLDING_MARKETS = {"cn"}`,即 **holdings 只支持 CN**;`fund` 亦为 CN-only。No web/auth fields.
- `.env` (gitignored) — `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` (see `core/llm.py:default_model()` — env value used as-is unless it carries a `[1m]` suffix, which is stripped/ignored because Claude Code's runtime leaks IDs like `glm-5.2[1m]` that compatible endpoints reject; hardcoded fallback is `claude-sonnet-4-5-20250929`, since `claude-sonnet-4-6` is **not** recognized by GLM-style Anthropic-compatible endpoints), `SMTP_PASSWORD`, and `TAVILY_KEY` (唯一 news/research key;cn-pivot 删掉了 `FINNHUB_KEY`/`ALPHAVANTAGE_KEY`,不再需要), and `INVESTBRIEF_DB_PATH` (SQLite DB 路径覆盖,见 `core/config.py:DB_PATH`)。
- `ANTHROPIC_AUTH_TOKEN` auto-aliases to `ANTHROPIC_API_KEY`.
- 全 akshare 数据源,无 yfinance。`run.py` 对 eastmoney 域名设置 NO_PROXY(系统代理 SSL 劫持会破坏 CN 行情/历史/资金流)。

## Architecture

**Domain-layer layout (refactor/modular-split):** packages are split by business domain, not tech layer. Dependency direction is strictly one-way — `run.py → pipelines → {market, holdings, risk, regime, mail} → {data, datasources} → core`. `strategies/*.yaml` are static config, loaded read-only by `risk/` and `holdings/etf/` through `core/strategy_loader.py` (not a domain layer). Domains have **ZERO 横向 dependencies** on each other (e.g., `market/` does not import `holdings/` or `mail/`; they collaborate only via `pipelines/`). Future changes must preserve this invariant.

**Extension seams (no plugin framework, just dict registry + DI):**
- New market → implement `MarketProvider` subclass in `market/<mkt>/` + register one line in `market/__init__.py:MARKET_PROVIDERS`.
- New report type → add a `pipelines/<name>.py` + dispatch entry in `run.py:run_once`.

### Email Pipeline (the only channel)

**Entry point:** `run.py` — a ~150-line CLI shell: `argparse` + proxy/env bootstrap + `main()`. `main()` parses args and dispatches to `run_once(args)`, which fans out to the right pipeline (`--only {macro,holdings,picks}`, default: all). All orchestration lives in `pipelines/`.

**Macro pipeline** (`pipelines/macro.py:run_macro_report`): `load config` → refresh data (CN `provider.refresh()` via `market.create_provider` + `GoldData.update_incremental()`, all resilient — fall back to stored latest on failure; refresh is DB-First fast-path, skipping when today's bars already exist) → collect CN macro (`CNMarketProvider`); `market_codes = [c for c in enabled_market_codes(config) if c != "us"]`(过渡保护,us 由外围卡替代) → **fetch 外围环境卡** (`market.overseas.fetch_overseas_data` + `render_overseas_card`:美联储利率静态常量/美债10Y `bond_zh_us_rate`/标普500 `index_us_stock_sina '.INX'`/USDCNY `forex_spot_em`,全 akshare) + news (`fetch_news`) → **compute P4 risk scores** (cn/gold via `RiskModel`, wrapped in `_safe_risk_score`) → **judge economic regime** (cn via `RegimeEngine`, wrapped in `_safe_regime_judge`;engine 本身通用,`judge(market)` 接受任意 market 字符串,但 pipeline 只对 cn 调用) → Claude ①⑥ (`market.macro_brief.generate_macro_brief` — one JSON call returning `(summary, risk)`, **`overseas_for_claude` + cn macro** + risk scores + regime data injected via `serialize_macro_context`) → **research views** (`market.research.fetch_research_views` + `generate_research_views`) → 拼装 sections:**overseas_html 置顶** + `MarketProvider.render_section` (CN + gold,each with `risk_html=` and `regime_html=`;gold 的 `render_gold_section` 已并入其 risk_html) → `mail.render.render_template` → `pipelines._send.send_report` (one email). On `--dry-run`, prints JSON instead of sending.

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

- `risk_indicators.yaml` — P4 risk indicator definitions (`common`/`cn`/`gold` 三个顶层分组;`common` 组的 indicator 仍为每个市场保留 `thresholds`/`low_thresholds` 子键,部分 `common` indicator 历史遗留也带 `us:` 阈值,但 `risk/config.py` 只为 cn/gold 装配指示器,`us` 阈值不再生效), consumed by `risk/config.py` (each indicator: `weight`, `category`, `thresholds`/`low_thresholds` per market, `invert`, `scale`, `unit`, `explain`). Replaces formerly-hardcoded indicator dicts.
- `etf_rules.yaml` — ETF analysis `rules[]`, consumed by `holdings/etf/engine.py`. Each rule: `id`, `enabled` (default true; toggle without deleting), `dimension`, `name`, `description`, `condition` (Python expr evaluated against a flattened indicators dict via `eval` with `_SAFE_BUILTINS`, no `__builtins__`), `signal` (bullish/bearish/neutral), `weight`. Replaces the deleted `holdings/etf/rules.json`.

### Risk Model (P4)

`investbrief/risk/` — market-cycle risk scoring (ported from StockCycleRiskDetector; that project's core). Produces a 0-100 risk score per market (cn/gold;us 指示器组已在 cn-pivot 中删除) from five weighted dimensions, with a state label and recommended action. **Tracking signal, not a prediction** — surfaced to Claude as context, never as a standalone buy/sell rule. **Indicator definitions (weights / thresholds / invert / scale / explain) are externalized to `strategies/risk_indicators.yaml`** — change thresholds by editing the YAML, no Python changes; loaded at runtime by `core/strategy_loader.py:load_strategy` (see Strategy files above).

- `models.py` — `RiskModel(data_source, indicators)`: indicators 由 pipeline 注入(各市场 `market/<mkt>/indicators.py` 工厂装配,见 `pipelines/macro.py:_build_indicators`);`calculate_score(market, date=None)` → `{total_score, state, risk_level, crash_prob, expected_return, action, dimensions, indicators}`. cn 含 valuation+technical+liquidity+sentiment+macro 维度;gold 用 gold_indicators。
- `config.py` — `MARKET_STATE_MAP` (score→state, 人读, used for report rendering) **and** `RISK_LEVEL_MAP` + `score_to_risk_level()` (score→`low`/`moderate`/`high`/`extreme`, used for decision branches / Claude prompt / future alert thresholds — two separate vocabularies kept apart on purpose). `FIVE_DIMENSIONS` (radar weights), `*_ALL_INDICATORS` (loaded from `strategies/risk_indicators.yaml` via `load_strategy`;`*_US_ALL_INDICATORS` 已删除,只保留 cn/gold), `BACKTEST_BUY_THRESHOLD=20` / `SELL_THRESHOLD=70`。
- `render.py` — `render_risk_card(score_data)` (CN card, injected into `MarketProvider.render_section` via `risk_html=`) + `render_gold_section(score_data)` (appended to `market_section_html`).

In the pipeline: `_safe_risk_score` wraps `calculate_score` (returns `{}` on failure → empty card, pipeline never blocks); scores are also serialized into the Claude context via `serialize_macro_context`. Preview without email: `scripts/preview_p4_risk.py`. Tests: `tests/test_risk_*.py`.

### Regime model (economic quadrant)

`investbrief/regime/` — a **second opinionated signal** alongside the risk model: the Browne permanent-portfolio quadrant from growth×inflation (繁荣/通胀/通缩/滞胀/中性). Same "tracking, not predicting" stance as risk.

- `engine.py` — `RegimeEngine(data_source).judge(market)` → `{quadrant, confidence, growth_axis, inflation_axis, indicators, market}`. GDP absolute values → YoY (`_yoy_from_absolute`); direction via trend voting (`_direction_vote`, needs ≥`DIRECTION_VOTE_MIN_AGREEING` agreeing periods); `_classify` maps growth×inflation to a quadrant (inflation-up also requires `CPI > INFLATION_UP_THRESHOLD`). Three de-noising layers: trend vote, CPI level threshold, and **switch confirmation** (`SWITCH_CONFIRMATION_RUNS=2` — re-judges on the lookback window and downgrades to 中性 if the quadrant changed, avoiding single-period noise). Module-level `_judge_from_series` etc. are pure functions with no DB access (unit-tested directly).
- `config.py` — `QUADRANTS` (占优资产 per quadrant for card annotation), thresholds, GDP/CPI `indicator` keys aligned with the data layer.
- `render.py` — `render_regime_card(data)`.

In the macro pipeline: `_safe_regime_judge` (returns `{}` on failure → empty card); the card is passed as `regime_html=` to `MarketProvider.render_section` (same data-only injection pattern as `risk_html=`), and `regime_data=` is serialized into `generate_macro_brief`. Reads only existing CPI (YoY) + GDP (absolute) series from `macro_data` — no new data sources. cn-pivot 后 pipeline **只对 cn 调用** `judge("cn")`;gold 不参与 regime。Tests: `tests/test_regime_engine.py` / `test_regime_render.py`.

> **Two different "regime" concepts — do not confuse.** This `regime/` package is the *macro economic quadrant* (cn-pivot 后只算 cn)。Separately, `holdings/regime_prompts.py` + `holdings/etf/indicators.py:_calc_regime` produce a *per-holding technical regime* (`trending_up`/`trending_down`/`volatile`/`sideways`) that is injected into the holdings Claude prompt as a hint. Different inputs, different consumers, different module.

### Research views (sell-side commentary)

`investbrief/market/research.py` — `fetch_research_views()`: Tavily search over the last 7 days restricted to a **whitelist of reputable outlets** (Reuters/Bloomberg/CNBC/FT/WSJ/MarketWatch/Barron's; CN: sina/wallstreetcn/caixin/yicai). Firm attribution is **title-based** (a firm is tagged only if it appears in the article *title*, never just the body — filters out roundup pages); items are tagged by market (美股 / A股·中国 / 全球其他). The same module also hosts `generate_research_views` (Claude synthesis via `call_claude`, `RESEARCH_VIEWS_PROMPT`) and `serialize_research_views`, invoked from `pipelines/macro.py` to render the `🏦 卖方机构观点` section. CN brokers (中信/华泰/申万) are intentionally out of scope — their views aren't in any free feed (verified). Tests: `tests/test_research_views.py`.

### Data Layer (stateful, P1)

`investbrief/data/` — SQLite-backed macro data layer (ported from StockCycleRiskDetector). The single source of truth for index/macro time series; providers read from here, they no longer fetch live per-call.

- `base.py` — `BaseData`: schema (`cn_index_daily` / `us_index_daily`(legacy DDL,us provider 已删,表保留不破坏存量数据) / `macro_data` / `sentiment_data` / `update_log` / `stock_daily`), `upsert_df` / `query` / `merge_sentiment_row` / `latest_bars(table, code, n)` / `latest_macro(indicator, country)` / `_retry_api`, plus a **DB-First fast-path** helper so `refresh()` skips fetching when today's bars already exist.
- `cn_data.py` — `CNData`: 5 A-share indices (`INDEX_CODES`) + LPR/M2/M1/社融/CN10Y/USDCNY (akshare;USDCNY 走 akshare `forex_spot_em`,cn-pivot 后零 yfinance)。
- `gold_data.py` — `GoldData`: gold price (akshare SGE) + US M2/CPI (FRED) with hardcoded 1980-2024 historical baselines.

DB at `data/macro_data.db` (gitignored; parent dir auto-created by `BaseData.conn`). Flow: provider `refresh()` → `data.update_incremental()` (per-method try/except, resilient), then `get_*` read latest bars/values. **Refresh failure → fall back to stored latest** (pipeline never blocks on one API). First deploy: `scripts/backfill_macro_data.py`; daily补数: `uv run run.py --update`. Constants live in `core/config.py` (`DB_PATH`, `API_RETRY_*`, `REPORTS_DIR`;`US_GDP_BASE_*` 已删除) — the old top-level `investbrief/config.py` is gone.

**eastmoney throttling (operational):** akshare hits eastmoney's data center, which rate-limits aggressively. Mitigations live in `datasources/akshare.py`: UA/Referer injection via a `Session.request` patch, `_with_retry` with random backoff (longer on the last retry), **negative caching** for `spot_em` and full-universe fetches (a failed full sweep is remembered, not re-attempted), and `get_stock_quote` via the bid_ask endpoint with name lookup. `run.py` force-bypasses the system proxy for eastmoney domains (NO_PROXY) — proxy SSL 劫持会破坏 CN quotes/history/flow。`holdings/analyzer` concurrency is capped at 2 to ease throttling.

### Providers

`investbrief/market/base.py` — `MarketProvider` ABC: `get_indices`, `get_monetary_policy`, `get_asset_performance`, `fetch_all`, `render_section`. `render_section` accepts opaque `risk_html=` and `regime_html=` kwargs (cross-domain injection — see Conventions). Concrete providers are registered in `market/__init__.py:MARKET_PROVIDERS` and instantiated via `create_provider(market)`.

| Package | Module | Role |
|---------|--------|------|
| `core/` | `llm.py` | `get_client()` cached client + `default_model()` + **`call_claude()` unified wrapper** |
| `core/` | `llm_errors.py` / `llm_json.py` | `classify_anthropic_error` / `extract_json` (json-repair fallback) |
| `core/` | `logging.py` / `textfmt.py` | centralized `setup_logging` / `md_inline` (Markdown→inline HTML) |
| `core/` | `strategy_loader.py` | `load_strategy(name)` — lru_cached YAML loader for `strategies/` |
| `core/` | `config.py` | `load_config` / `validate_config` / `validate_holdings` + constants (`DB_PATH`, `API_RETRY_*`, `REPORTS_DIR`;`US_GDP_BASE_*` 已删) — formerly top-level `investbrief/config.py` |
| `strategies/` | `risk_indicators.yaml` / `etf_rules.yaml` / `pick_profiles.yaml` | Externalized P4 indicator config / ETF analysis rules / A 股选股 profile (YAML) |
| `data/` | `base.py` / `cn_data.py` / `gold_data.py` | **Stateful SQLite data layer** (P1) — providers read index/macro series from here; DB-First refresh fast-path;`us_data.py` 已删,见 Data Layer above |
| `datasources/` | `akshare.py` / `tavily.py` / `_common.py` | **API adapters** — cn-pivot 后只剩 akshare(含外围环境新方法 `get_us_treasury_10y`/`get_sp500_quote`/`get_fx_usdcny_realtime`/`get_cn_qvix`) + Tavily(news/research)。`yfinance.py`/`finnhub.py`/`alphavantage.py` 已删。`akshare.py` carries eastmoney throttling mitigations (UA/Referer, negative cache, backoff, `get_stock_quote`) |
| `market/` | `base.py` | `MarketProvider` ABC (macro methods + `render_section` with `risk_html=`/`regime_html=`) |
| `market/` | `__init__.py` | `MARKET_PROVIDERS` registry (`{"cn": CNMarketProvider, "gold": GoldMarketProvider}`;**无 us**) + `create_provider(market)` factory |
| `market/` | `macro_brief.py` | `MACRO_BRIEF_PROMPT` + `serialize_macro_context` + `generate_macro_brief` (Claude ①⑥, one JSON call → `(summary, risk)` tuple via `call_claude`+`extract_json`;上下文注入 overseas_for_claude + cn macro) |
| `market/` | `research.py` | `fetch_research_views` (Tavily) + `RESEARCH_VIEWS_PROMPT` + `serialize_research_views` + `generate_research_views`; see Research views above |
| `market/` | `overseas.py` | **外围环境卡**(cn-pivot 新增)— `fetch_overseas_data(ak_client)` + `render_overseas_card(data)`:美联储利率(静态常量)/美债10Y/标普500/USDCNY,全 akshare,零 yfinance。由 `pipelines/macro.py` 置顶插入 sections |
| `market/cn/` | `provider.py` / `calendar.py` / `news.py` / `indicators.py` | `CNMarketProvider` — akshare macro (indices, LPR/M2/社融/国债, USDCNY); A-share calendar (LPR/PMI/CPI/PPI/M2); A-share news;`indicators.py` 承载 CN 专属计算(如 QVIX) |
| `market/gold/` | `provider.py` / `indicators.py` | `GoldMarketProvider` — 黄金 section(akshare SGE 价格 + FRED M2/CPI);`render_section` 透传(gold 的 risk_html 已包含 `render_gold_section` 输出) |
| `risk/` | `models.py` / `config.py` / `render.py` | **Market-cycle risk model** (P4) — `RiskModel.calculate_score` for **cn/gold**(us 已删); 5 weighted dimensions; `state` (人读) + `risk_level` (low/moderate/high/extreme); indicators loaded from `strategies/risk_indicators.yaml`; see Risk Model above |
| `regime/` | `engine.py` / `config.py` / `render.py` | **Economic-quadrant regime** — `RegimeEngine.judge` (Browne growth×通胀); reads GDP+CPI from `macro_data`;pipeline 只对 cn 调用; see Regime model above |
| `holdings/` | `analyzer.py` / `brief.py` / `renderer.py` / `regime_prompts.py` + `etf/{analyzer,engine,indicators}` | **Holdings email pipeline** — per-recipient analysis (**CN only**: stock/etf/fund); `_with_ai`/`generate_stock_conclusion` adds Claude single-stock brief (`_fallback_stock_conclusion` rule-based on failure); `_extract_technicals` produces 18 technical fields; `regime_prompts.py` injects the **per-holding technical regime** hint; the former `etf/rules.json` is externalized to `strategies/etf_rules.yaml` |
| `picks/` | `engine.py` / `factors.py` / `universe.py` / `profiles.py` / `data.py` / `cache.py` / `renderer.py` / `brief.py` | **A 股 selection email pipeline** — 3 个 profile(由 `strategies/pick_profiles.yaml` 定义)各选 Top1;`engine.py` 编排筛选+打分,`factors.py` 因子计算,`universe.py` 股票池,`cache.py` 日级缓存,`renderer.py` 渲染卡片,`brief.py` Claude 研判 |
| `mail/` | `sender.py` | `EmailSender` — SMTP with retry; `send` + `send_bulk(messages)→(sent, failed)` (one connection for N recipients) |
| `mail/` | `render.py` | **Jinja2** template-rendering library: `load_template` / `render_template` / `render_holdings_template`. Chinese-only; `autoescape=False` (vars are pre-rendered HTML fragments); `language` arg accepted but ignored. `translate_html` was deleted. Formerly top-level `report.py` |
| `mail/` | `templates/{email_base,email_holdings,email_picks}.j2` | Jinja2 templates (`.j2`) |
| `pipelines/` | `macro.py` / `holdings.py` / `picks.py` / `scheduler.py` / `_send.py` | **Pipeline orchestration** — `run_macro_report` + `fetch_news` + `_safe_risk_score` + `_safe_regime_judge`; `run_holdings_report`; `run_picks_report`(A 股 selection); `run_scheduler` / `first_enabled_cron` / `_run_scheduled_macro`; `send_report` helper |

### Macro data sources (verified,全 akshare + FRED)

- **外围环境**(akshare,由 `market/overseas.py` + `datasources/akshare.py` 装配):美联储基金利率 = 静态常量 `FED_FUNDS_RATE`(FOMC 调整时手动更新);美债10Y `bond_zh_us_rate`(取最新一行"美国国债收益率10年");标普500 `index_us_stock_sina(symbol=".INX")`(最新点数 + 前日涨跌幅%);USDCNY `forex_spot_em`(代码 USDCNYC;`fx_spot_quote` 实测全 NaN,不可用);CN QVIX `index_option_50etf_qvix` / `index_option_300etf_qvix`(恐慌指数,50ETF 与 300ETF 双口径)。**零 yfinance**。
- CN monetary: akshare `macro_china_lpr` (LPR1Y/5Y), `macro_china_money_supply` (M2/M1 YoY), `macro_china_shrzgm` (社融), `bond_china_yield` (CN 10Y, filter 中债国债收益率曲线);FX: USDCNY = akshare `forex_spot_em`。
- 黄金: akshare SGE 价格 + FRED (US M2/CPI,用于 gold risk indicator)。`GoldData` 内置 1980-2024 历史 baseline。
- **akshare frames are inconsistently ordered** — always sort by date/month column descending for latest, never rely on position.
- CN-US yield spread:Claude 看到外围卡的「美债10Y」+ CN section 的「CN 10Y」(两值分别透传,pipeline 不显式相减),可自行推演利差。

### Report structure (email)

`mail/templates/email_base.j2`: header (宏观日报 title) → ① 核心观点 (`.summary-box`, Claude) → `{{market_sections}}` (**外围环境卡置顶** + A 股主 section (大类资产 / 货币政策 / 经济日历 / QVIX 恐慌指数 + a P4 risk card + an economic-regime card) + gold section) → 🏦 卖方机构观点 (`{{research_views}}`, Claude) → ⑥ 风险提示与下周关注 → news → footer. `mail.render.render_template` passes `report_data` into the Jinja2 environment (keys `macro_summary` / `risk_outlook` / `market_section_html` / `research_views` / `news` map to the template placeholders).

The **holdings email** (`mail/templates/email_holdings.j2`, separate from macro) renders per-recipient (**CN only**): header → `{{holdings_summary}}` (Claude 组合研判) → `{{holdings_sections}}` (one card per holding). Each card shows available dimensions by `type`: price/NAV, rating distribution + **multi-period trend** (本期 vs 上期, pct-point) + analyst actions + price target, fundamentals (PE/ROE/returns), technicals (MA/RSI/MACD + 18-field `_extract_technicals`, via `holdings/etf/indicators.py`), flow (CN only), news, and an AI single-stock conclusion (`ai_conclusion`). Missing dimensions degrade gracefully. `mail.render.render_holdings_template` passes the data dict into Jinja2.

## Key Conventions

- Pipeline is resilient: API failures log warnings and continue with empty data / fallback. Claude failure (call_claude returns None) → ①⑥ use placeholder strings, report still sends.
- Color scheme: Chinese convention — red = up, green = down (`#e74c3c` / `#27ae60`).
- **数据源全 akshare + FRED + Tavily,零 yfinance** — cn-pivot 后已删 `datasources/yfinance.py`/`finnhub.py`/`alphavantage.py`。新数据需求优先走 `datasources/akshare.py`(CN/外围/黄金),news/research 走 Tavily,US M2/CPI(gold indicator)走 FRED。如需引入新数据源,加到 `datasources/` 并经 `data/` 层落库,不要绕过数据层直接在 provider 里 inline fetch。
- **Domain-layer invariant** — domains (`market/`, `holdings/`, `risk/`, `regime/`, `mail/`) must not import each other; they collaborate only through `pipelines/`. Lower layers (`data/`, `datasources/`) never reach up. Preserve this when adding code.
- **Cross-domain collaboration is data-only.** Cross-domain render injection is allowed *only* when the handoff is **data through `pipelines/`**, never an import. Two canonical instances: (1) `risk/render.py:render_risk_card` HTML → passed to `MarketProvider.render_section(..., risk_html=...)`; (2) `regime/render.py:render_regime_card` HTML → passed to `render_section(..., regime_html=...)`. `market/` never imports `risk/` or `regime/`; it only accepts opaque HTML strings. Follow this pattern for any future cross-domain render injection.
- **All Claude calls go through `core.llm.call_claude`** (error classification + backoff + None-on-failure). JSON-shaped responses go through `core.llm_json.extract_json`. Do not call `client.messages.create` inline or hand-roll JSON parsing.
- **Tunable strategy config lives in `strategies/*.yaml`**, loaded via `core.strategy_loader.load_strategy` (lru_cached). Do not hardcode indicator weights/thresholds or ETF rule definitions in Python; edit the YAML.
- Adding a new macro section: add a `get_*` method to `MarketProvider` ABC in `market/base.py` + CN implementation in `market/cn/`(以及 gold 实现在 `market/gold/`,如适用) + a `_render_*` helper called from `render_section` + include the new field in `market.macro_brief.serialize_macro_context` so Claude sees it. 外围环境类信号(非 cn 本土)加到 `market/overseas.py` 而非 provider。
- Adding a new market: implement a `MarketProvider` subclass under `market/<mkt>/` + register one line in `market/__init__.py:MARKET_PROVIDERS`. No `run.py` core changes needed — `create_provider(market)` picks it up. (Data-layer and datasource support must obviously exist first.)
- Adding a new report type: add `pipelines/<name>.py` with a `run_<name>_report(args)` + dispatch entry in `run.py:run_once`.
- Anthropic client: always via `investbrief.core.llm.get_client()` (don't construct `anthropic.Anthropic(...)` inline).
- Previews saved to `reports/preview_macro.html` (and `reports/preview_holdings.html` for the holdings pipeline) after each non-dry-run.
- Model configurable via `ANTHROPIC_DEFAULT_SONNET_MODEL` (see Configuration for the `[1m]` filtering quirk).

## CI/CD

### PR Check (`.github/workflows/pr-check.yml`)
`pull_request` to main → `uv sync --frozen` (lockfile consistency) + `uv run ruff check .` (pyproject select E9/F/UP: 致命错误 + pyflakes + pyupgrade) + `uv run pytest tests/ -q -m "not network"` (real-API tests excluded via the `network` marker). + `uv run python scripts/check_domain_boundary.py` (域边界 lint).

### Docker Publish (`.github/workflows/docker-publish.yml`)
`push` to main → builds ONE multi-arch (amd64+arm64) image: `ghcr.io/dragonl641/invest-brief` (scheduler). Trivy scan + SARIF.

## Deployment

### Local (`docker-compose.yml`)
Single `scheduler` service, builds from `Dockerfile.scheduler`. Mounts config.json/.env (ro), logs/, reports/, data/ (stateful SQLite, P1). **首次启动前置**:`config.json`/`.env` 不存在时单文件 bind mount 会被 Docker 建成目录(常见 footgun),需先 `cp config.example.json config.json && cp .env.example .env` 再 `docker compose up`。

### Prod (`docker-compose.prod.yml`)
Pulls `ghcr.io/dragonl641/invest-brief:latest`. Same mounts.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

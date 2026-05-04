# A 股简报功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 invest-brief 新增 A 股（沪深）市场简报，与美股简报完全独立运行，使用 AKShare 获取数据。

**Architecture:** 重构 `lib/` 为 `investbrief/` 包，按市场分子包（`us/`、`cn/`、`core/`）。抽象 `MarketProvider` 基类定义统一接口。Pipeline 按市场独立调度、独立构建、独立发送。

**Tech Stack:** Python 3.10+, AKShare（A股数据）, yfinance（美股数据，不变）, Claude API（AI摘要）, matplotlib（图表）, Jinja-style 模板

---

## Phase 1: Project Restructuring

> 将 `lib/` 重构为 `investbrief/` 包结构。完成后 `uv run run.py --now --market us` 行为和迁移前完全一致。

### Task 1: Create package structure + MarketProvider ABC

**Files:**
- Create: `investbrief/__init__.py`
- Create: `investbrief/core/__init__.py`
- Create: `investbrief/us/__init__.py`
- Create: `investbrief/cn/__init__.py`
- Create: `investbrief/core/provider.py`

- [ ] **Step 1: Create directories**

```bash
mkdir -p investbrief/core investbrief/us investbrief/cn
```

- [ ] **Step 2: Create `investbrief/core/provider.py`**

```python
"""Market provider abstract base class."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class MarketProvider(ABC):
    """各市场数据获取和渲染的统一接口。"""

    market_code: str = ""
    country_name: str = ""
    currency: str = "$"

    @abstractmethod
    def get_indices(self) -> list[dict[str, Any]]:
        """获取主要指数行情。"""

    @abstractmethod
    def get_holdings_data(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """获取持仓个股详情。"""

    @abstractmethod
    def get_recommendations(self, industries: list[str], exclude: list[str] | None = None) -> list[dict[str, Any]]:
        """按行业获取推荐关注个股。"""

    @abstractmethod
    def fetch_all(self, holdings: list[dict], industries: list[str]) -> dict[str, Any]:
        """获取该市场全部数据，返回供 report 使用的 dict。"""

    @abstractmethod
    def render_section(self, data: dict[str, Any], config: dict[str, Any]) -> str:
        """渲染该市场的 HTML 区块。"""
```

- [ ] **Step 3: Create `__init__.py` files**

`investbrief/__init__.py`:
```python
"""invest-brief: personalized daily investment briefing."""
```

`investbrief/core/__init__.py`:
```python
from .provider import MarketProvider

__all__ = ["MarketProvider"]
```

`investbrief/us/__init__.py`:
```python
```

`investbrief/cn/__init__.py`:
```python
```

- [ ] **Step 4: Commit**

```bash
git add investbrief/
git commit -m "feat: create investbrief package structure with MarketProvider ABC"
```

---

### Task 2: Move core modules (no internal deps)

**Files:**
- Create: `investbrief/core/charts.py` (from `lib/charts.py`)
- Create: `investbrief/core/mailer.py` (from `lib/smtp_client.py`)
- Create: `investbrief/core/guards.py` (from `lib/guards.py`)
- Create: `investbrief/core/models.py` (from `lib/models.py`)

These four modules have **zero internal imports** — they only import external packages. The move is mechanical: copy file, no import changes needed.

- [ ] **Step 1: Copy files to new locations**

```bash
cp lib/charts.py investbrief/core/charts.py
cp lib/smtp_client.py investbrief/core/mailer.py
cp lib/guards.py investbrief/core/guards.py
cp lib/models.py investbrief/core/models.py
```

No import changes needed — these files only import `logging`, `matplotlib`, `smtplib`, `pydantic`, etc.

- [ ] **Step 2: Commit**

```bash
git add investbrief/core/
git commit -m "refactor: move core modules (charts, mailer, guards, models) to investbrief/core"
```

---

### Task 3: Move US modules

**Files:**
- Create: `investbrief/us/clients.py` (from `lib/api_clients.py`)
- Create: `investbrief/us/news.py` (from `lib/data_provider.py`)
- Create: `investbrief/us/watchlist.py` (from `lib/watchlists.py`)
- Create: `investbrief/us/calendar.py` (from `lib/economic_calendar.py`)
- Create: `investbrief/us/congress.py` (from `lib/congressional_tracker.py`)
- Create: `investbrief/us/insider.py` (from `lib/insider_tracker.py`)

Import changes needed:

| File | Old Import | New Import |
|------|-----------|------------|
| `us/news.py` | `from .api_clients import ...` | `from .clients import ...` |
| `us/news.py` | `from .api_clients import ...` (绝对路径) | `from investbrief.us.clients import ...` |

`us/clients.py`, `us/watchlist.py`, `us/calendar.py`, `us/congress.py`, `us/insider.py` — **no internal imports**, only external packages. Copy as-is.

- [ ] **Step 1: Copy files that need no changes**

```bash
cp lib/api_clients.py investbrief/us/clients.py
cp lib/watchlists.py investbrief/us/watchlist.py
cp lib/economic_calendar.py investbrief/us/calendar.py
cp lib/congressional_tracker.py investbrief/us/congress.py
cp lib/insider_tracker.py investbrief/us/insider.py
```

- [ ] **Step 2: Copy `data_provider.py` → `us/news.py` and update imports**

Copy the file:
```bash
cp lib/data_provider.py investbrief/us/news.py
```

In `investbrief/us/news.py`, change:
```python
# OLD (lines near top):
from .api_clients import FinnhubClient, AlphaVantageClient, TavilyClient, get_available_apis

# NEW:
from .clients import FinnhubClient, AlphaVantageClient, TavilyClient, get_available_apis
```

If the original uses absolute imports (`from lib.api_clients import ...`), change to `from investbrief.us.clients import ...`.

- [ ] **Step 3: Commit**

```bash
git add investbrief/us/
git commit -m "refactor: move US market modules to investbrief/us"
```

---

### Task 4: Move USMarketProvider + add fetch_all

**Files:**
- Create: `investbrief/us/provider.py` (from `lib/market.py`)

This is the most complex move. `USMarketProvider` must:
1. Inherit from `MarketProvider` ABC
2. Update imports to new paths
3. Add `fetch_all()` method that encapsulates all US-specific data fetching (currently scattered in `run.py`'s `fetch_market_data()`)

- [ ] **Step 1: Copy `lib/market.py` → `investbrief/us/provider.py`**

```bash
cp lib/market.py investbrief/us/provider.py
```

- [ ] **Step 2: Update imports in `investbrief/us/provider.py`**

Replace the top imports:
```python
# OLD:
from .api_clients import YFinanceClient
from .charts import generate_stock_chart
from .watchlists import get_watchlist_stocks, INDUSTRY_LABELS

# NEW:
from .clients import YFinanceClient
from investbrief.core.charts import generate_stock_chart
from .watchlist import get_watchlist_stocks, INDUSTRY_LABELS
```

- [ ] **Step 3: Add `MarketProvider` inheritance and `fetch_all`**

Add import at top:
```python
from investbrief.core.provider import MarketProvider
```

Change class declaration:
```python
# OLD:
class USMarketProvider:
    market_code = "us"
    country_name = "美国市场"
    flag = "🇺🇸"

# NEW:
class USMarketProvider(MarketProvider):
    market_code = "us"
    country_name = "美国市场"
    currency = "$"
    flag = "🇺🇸"
```

Add `fetch_all` method to the class (this moves logic currently in `run.py::fetch_market_data`):
```python
def fetch_all(self, holdings: list[dict], industries: list[str]) -> dict[str, Any]:
    """获取美股全部数据。"""
    from .calendar import get_upcoming_events
    from .congress import get_recent_congressional_trades
    from .insider import get_form4_filings

    holdings_symbols = [h["symbol"] for h in holdings]

    indices = self.get_indices()
    holdings_data = self.get_holdings_data(holdings)
    recommendations = self.get_recommendations_from_industries(industries, holdings_symbols)
    premarket = self.get_premarket_movers(holdings_symbols)
    earnings = self.get_earnings_calendar(holdings, recommendations)
    economic = get_upcoming_events()

    holdings_symbols_set = set(holdings_symbols)
    congressional = get_recent_congressional_trades(tickers=holdings_symbols)

    # SEC EDGAR insider filings per holding (already fetched in get_holdings_data)
    # Just need the congressional and economic calendar here

    return {
        "indices": indices,
        "holdings": holdings_data,
        "recommendations": recommendations,
        "premarket_movers": premarket,
        "earnings_calendar": earnings,
        "economic_calendar": economic,
        "congressional_trades": congressional,
    }
```

Note: The existing `get_holdings_data` already calls `get_form4_filings` per holding internally. Verify this by reading the current `lib/market.py`. If `get_holdings_data` doesn't include insider data, add the per-holding insider fetch here.

- [ ] **Step 4: Verify the file has no remaining `from lib.` imports**

```bash
grep -n "from lib\." investbrief/us/provider.py
# Expected: no output
```

- [ ] **Step 5: Commit**

```bash
git add investbrief/us/provider.py
git commit -m "refactor: move USMarketProvider, inherit MarketProvider, add fetch_all"
```

---

### Task 5: Move send_report → investbrief/report.py + decouple from providers

**Files:**
- Create: `investbrief/report.py` (from `lib/send_report.py`)

Key change: `render_template` currently imports `USMarketProvider` directly to call `provider.render_section()`. After this change, the rendered HTML is passed in via `data["market_section_html"]`, so `report.py` no longer imports any provider.

- [ ] **Step 1: Copy `lib/send_report.py` → `investbrief/report.py`**

```bash
cp lib/send_report.py investbrief/report.py
```

- [ ] **Step 2: Update imports**

```python
# OLD:
from lib.smtp_client import EmailSender

# NEW:
from investbrief.core.mailer import EmailSender
```

Remove the `sys.path.insert` line if present.

- [ ] **Step 3: Decouple `render_template` from `USMarketProvider`**

Find the section in `render_template` that creates `USMarketProvider()` and calls `render_section`. Replace:

```python
# OLD (inside render_template):
from lib.market import USMarketProvider
provider = USMarketProvider()
us_html = provider.render_section(data.get("us", {}), config)
html = html.replace("{{market_sections}}", us_html)

# NEW:
market_html = data.get("market_section_html", "")
html = html.replace("{{market_sections}}", market_html)
```

- [ ] **Step 4: Verify no remaining `from lib.` imports**

```bash
grep -n "from lib\." investbrief/report.py
# Expected: no output
```

- [ ] **Step 5: Commit**

```bash
git add investbrief/report.py
git commit -m "refactor: move report module, decouple from specific providers"
```

---

### Task 6: Update run.py — new imports + --market argument + pipeline refactor

**Files:**
- Modify: `run.py`

This is the largest change. `run.py` must:
1. Change all `from lib.*` imports to `from investbrief.*`
2. Add `--market` as required argument
3. Refactor `run_once` to be market-aware
4. Move US-specific data fetching into `USMarketProvider.fetch_all()`
5. Pass pre-rendered `market_section_html` to report

- [ ] **Step 1: Update CLI arguments in `main()`**

Find `argparse` section. Add `--market` as required argument:

```python
# ADD to argument parser:
parser.add_argument(
    "--market",
    required=True,
    choices=["us", "cn", "all"],
    help="Market to run: us, cn, or all",
)
```

Update `run_once(args)` to use `args.market`:

```python
def run_once(args):
    market = args.market
    if market == "all":
        for m in ["us", "cn"]:
            _run_single_market(m, args)
    else:
        _run_single_market(market, args)
```

- [ ] **Step 2: Create `_run_single_market(market, args)`**

Extract the core logic from current `run_once` into `_run_single_market`:

```python
def _run_single_market(market: str, args):
    """单个市场的完整流程。"""
    config = load_config()
    recipients = _filter_recipients(config["recipients"], market)
    if not recipients:
        logger.info(f"No active recipients for market '{market}', skipping.")
        return

    holdings, industries = merge_recipient_settings(recipients, market)
    provider = _create_provider(market)

    # Fetch data
    market_data = provider.fetch_all(holdings, industries)
    news = fetch_news(config, [h["symbol"] for h in holdings], NEWS_LIMIT, industries)
    news_summary = summarize_news(news) if not (args and hasattr(args, 'skip_summary') and args.skip_summary) else []
    daily_summary = generate_daily_summary(market_data, news, holdings) if not (args and hasattr(args, 'skip_summary') and args.skip_summary) else ""

    # Render market section HTML
    market_html = provider.render_section(market_data, config)

    # Build and send report
    report_data = build_report_data(market, market_html, market_data, news, news_summary, daily_summary)
    send_report(report_data, config, recipients)
```

- [ ] **Step 3: Update imports**

Replace all deferred imports:

```python
# OLD:
from lib.market import USMarketProvider
from lib.economic_calendar import get_upcoming_events
from lib.congressional_tracker import get_recent_congressional_trades
from lib.insider_tracker import get_form4_filings
from lib.data_provider import DataProvider
from lib.models import NewsSummaryResponse
from lib.guards import EarningsGuard, PostAIGuard
from lib.send_report import load_config as sr_load_config, load_template, render_template, translate_html
from lib.smtp_client import EmailSender

# NEW:
from investbrief.us.provider import USMarketProvider
from investbrief.us.news import DataProvider
from investbrief.core.models import NewsSummaryResponse
from investbrief.core.guards import EarningsGuard, PostAIGuard
from investbrief.report import load_config as sr_load_config, load_template, render_template, translate_html
from investbrief.core.mailer import EmailSender
```

Note: `get_upcoming_events`, `get_recent_congressional_trades`, `get_form4_filings` are no longer imported directly in `run.py` — they're now called inside `USMarketProvider.fetch_all()`.

- [ ] **Step 4: Add `_create_provider` factory function**

```python
def _create_provider(market: str) -> MarketProvider:
    """根据市场类型创建 provider 实例。"""
    if market == "us":
        return USMarketProvider()
    elif market == "cn":
        from investbrief.cn.provider import CNMarketProvider
        return CNMarketProvider()
    else:
        raise ValueError(f"Unknown market: {market}")
```

- [ ] **Step 5: Add `_filter_recipients` function**

```python
def _filter_recipients(recipients: list, market: str) -> list:
    """筛选在指定市场有配置的活跃 recipient。"""
    result = []
    for r in recipients:
        if not r.get("active", True):
            continue
        markets = r.get("markets", {})
        market_cfg = markets.get(market, {})
        if market_cfg.get("holdings") or market_cfg.get("industries"):
            result.append(r)
    return result
```

- [ ] **Step 6: Update `merge_recipient_settings` for new config structure**

```python
# OLD:
def merge_recipient_settings(recipients: list) -> tuple:
    # reads r["settings"]["holdings"], r["settings"]["industries"]

# NEW:
def merge_recipient_settings(recipients: list, market: str) -> tuple:
    """合并指定市场下所有 recipient 的持仓和行业。"""
    all_holdings = []
    seen_symbols = set()
    all_industries = set()
    for r in recipients:
        market_cfg = r.get("markets", {}).get(market, {})
        for h in market_cfg.get("holdings", []):
            key = h.get("symbol", "")
            if key and key not in seen_symbols:
                seen_symbols.add(key)
                all_holdings.append(h)
        all_industries.update(market_cfg.get("industries", []))
    return all_holdings, list(all_industries)
```

- [ ] **Step 7: Update `build_report_data` for new structure**

```python
def build_report_data(market: str, market_html: str, market_data: dict,
                      news: list, news_summary: list, daily_summary: str) -> dict:
    """构建报告数据 dict。"""
    market_names = {"us": "美股日报", "cn": "A股日报"}
    now = datetime.now(ZoneInfo("Asia/Shanghai"))

    return {
        "subject": market_names.get(market, "投资日报"),
        "data_time": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "global_metrics": build_global_metrics(market_data.get("indices", [])),
        "market_section_html": market_html,
        "news": news_summary if news_summary else news,
        "daily_summary": daily_summary,
        "market": market,
    }
```

- [ ] **Step 8: Update `send_report` to use new config structure**

The current `send_report` reads `r["settings"]` for language and other per-recipient config. Update to read from the appropriate market section:

```python
def send_report(report_data: dict, config: dict, recipients: list):
    """渲染并发送报告。"""
    template = load_template()

    for r in recipients:
        language = r.get("language", "zh-CN")
        html = render_template(template, report_data, language, r)

        # 翻译
        if language != "zh-CN":
            html = translate_html(html, language)

        sender = EmailSender()
        success = sender.send(
            to_email=r["email"],
            subject=report_data["subject"],
            html_content=html,
        )
        if success:
            logger.info(f"Report sent to {r['email']}")
        else:
            logger.error(f"Failed to send report to {r['email']}")
```

- [ ] **Step 9: Update `fetch_news` for market awareness**

The current `fetch_news` uses `DataProvider` (US news). For CN market, we'll use a different news source. Add market parameter:

```python
def fetch_news(config, tickers, max_news_count, industries, market="us"):
    """获取新闻。"""
    if market == "us":
        provider = DataProvider(config)
        return provider.get_financial_news(
            tickers=tickers,
            limit=max_news_count,
            user_tickers=tickers,
            industries=industries,
        )
    elif market == "cn":
        from investbrief.cn.news import fetch_cn_news
        return fetch_cn_news(tickers, industries, max_news_count)
    return []
```

- [ ] **Step 10: Update scheduler for multi-market**

```python
def run_scheduler(config):
    """启动调度器，每个市场独立 cron。"""
    import schedule  # or croniter-based scheduling

    markets_cfg = config.get("markets", {})
    for market, cfg in markets_cfg.items():
        if not cfg.get("enabled", False):
            continue
        schedule_cron = cfg.get("schedule", {})
        cron_expr = schedule_cron.get("cron", "")
        # Set up cron job for this market using croniter
        logger.info(f"Scheduled {market} market with cron: {cron_expr}")
    # ... existing scheduler loop
```

- [ ] **Step 11: Verify all `from lib.` imports are removed**

```bash
grep -n "from lib\." run.py
# Expected: no output
```

- [ ] **Step 12: Commit**

```bash
git add run.py
git commit -m "refactor: update run.py for multi-market pipeline with --market argument"
```

---

### Task 7: Migrate config structure

**Files:**
- Modify: `config.example.json`

- [ ] **Step 1: Update `config.example.json` to new structure**

```json
{
  "markets": {
    "us": {
      "enabled": true,
      "schedule": {
        "cron": "0 23 * * 1-5",
        "timezone": "Asia/Shanghai"
      }
    },
    "cn": {
      "enabled": false,
      "schedule": {
        "cron": "0 17 * * 1-5",
        "timezone": "Asia/Shanghai"
      }
    }
  },
  "email_service": {
    "provider": "qq",
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender_email": "YOUR_EMAIL@qq.com",
    "sender_name": "投资简报"
  },
  "recipients": [
    {
      "id": 1,
      "email": "recipient@example.com",
      "name": "Recipient1",
      "active": true,
      "language": "zh-CN",
      "markets": {
        "us": {
          "industries": ["semiconductor_ai", "aerospace_defense"],
          "holdings": [
            {"symbol": "AMD", "name": "AMD"},
            {"symbol": "NVDA", "name": "NVIDIA"}
          ],
          "news_count": 10
        }
      }
    }
  ]
}
```

Key changes from old config:
- `schedule` → `markets.us.schedule` + `markets.cn.schedule`
- `recipients[].settings` → `recipients[].markets.us` / `recipients[].markets.cn`
- CN section is `enabled: false` by default (Phase 3 will enable it)

- [ ] **Step 2: Update `load_config` in `run.py` if needed**

If `load_config` does any validation or transformation of the old config structure, update it to handle the new structure. The function should read `config["markets"]` instead of `config["schedule"]`.

- [ ] **Step 3: Commit**

```bash
git add config.example.json
git commit -m "refactor: update config template for multi-market structure"
```

---

### Task 8: Verify Phase 1 — US market works identically

- [ ] **Step 1: Update your `config.json` to new structure**

Copy from `config.example.json`, fill in your actual values. Move your old `settings` block under `markets.us`.

- [ ] **Step 2: Run dry-run to verify**

```bash
uv run run.py --dry-run --market us
```

Expected: JSON output to stdout with US market data, same structure as before migration. No import errors.

- [ ] **Step 3: Run actual send to verify**

```bash
uv run run.py --now --market us
```

Expected: Email received with same content as pre-migration.

- [ ] **Step 4: Delete `lib/` directory**

Once verified:
```bash
rm -rf lib/
git add -A
git commit -m "refactor: remove old lib/ directory after successful migration"
```

---

## Phase 2: A-Share Data Layer

> 实现 AKShare 客户端和 A 股辅助模块。每个模块可独立验证。

### Task 9: Add akshare dependency + implement cn/client.py core

**Files:**
- Modify: `pyproject.toml`
- Create: `investbrief/cn/client.py`

- [ ] **Step 1: Add akshare to dependencies**

In `pyproject.toml`, add `"akshare"` to `dependencies` list.

If `run.py` has PEP 723 inline metadata (`# /// script` block), also add `akshare` there.

```bash
uv sync
```

- [ ] **Step 2: Create `investbrief/cn/client.py` with core methods**

```python
"""A股数据客户端，基于 AKShare。"""

import logging
from typing import Any, Optional
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class AKShareClient:
    """封装 AKShare 接口，提供统一的 A 股数据获取方法。

    每个方法内部做异常处理和空值兜底，单个接口失败不影响整体。
    AKShare 接口可能因上游网站变更而失效，调用时需注意。
    """

    # ---- 指数 ----

    def get_index_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取指数实时行情。

        Args:
            symbol: 指数代码，如 "000001"（上证指数）、"399001"（深证成指）
        """
        try:
            df = ak.stock_zh_index_spot_em(symbol=symbol)
            if df is None or df.empty:
                return None
            row = df.iloc[0]
            return {
                "symbol": symbol,
                "name": row.get("名称", ""),
                "price": float(row.get("最新价", 0)),
                "change": float(row.get("涨跌额", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
                "volume": float(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
            }
        except Exception as e:
            logger.warning(f"AKShare get_index_quote failed for {symbol}: {e}")
            return None

    # ---- 个股行情 ----

    def get_stock_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取个股实时行情。

        Args:
            symbol: 6位股票代码，如 "600519"
        """
        try:
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return {
                "symbol": symbol,
                "name": r.get("名称", ""),
                "price": float(r.get("最新价", 0)),
                "change": float(r.get("涨跌额", 0)),
                "change_pct": float(r.get("涨跌幅", 0)),
                "open": float(r.get("今开", 0)),
                "high": float(r.get("最高", 0)),
                "low": float(r.get("最低", 0)),
                "volume": float(r.get("成交量", 0)),
                "amount": float(r.get("成交额", 0)),
                "market_cap": float(r.get("总市值", 0)),
                "pe": self._safe_float(r.get("市盈率-动态")),
                "turnover_rate": self._safe_float(r.get("换手率")),
                "52wk_high": self._safe_float(r.get("年初至今涨跌幅")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_stock_quote failed for {symbol}: {e}")
            return None

    # ---- 历史K线 ----

    def get_stock_history(self, symbol: str, days: int = 180) -> pd.DataFrame | None:
        """获取个股日K线历史数据。

        Args:
            symbol: 6位股票代码
            days: 获取最近多少天的数据
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is None or df.empty:
                return None
            # 标准化列名
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "涨跌幅": "change_pct", "涨跌额": "change",
                "换手率": "turnover",
            })
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.warning(f"AKShare get_stock_history failed for {symbol}: {e}")
            return None

    @staticmethod
    def _safe_float(val) -> float | None:
        """安全转换为 float。"""
        if val is None or val == "-" or val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
```

- [ ] **Step 3: Verify core methods work**

```bash
uv run python -c "
from investbrief.cn.client import AKShareClient
c = AKShareClient()
print('=== Index Quote ===')
print(c.get_index_quote('000001'))
print('=== Stock Quote ===')
print(c.get_stock_quote('600519'))
print('=== Stock History (last 5 rows) ===')
df = c.get_stock_history('600519', days=30)
if df is not None:
    print(df.tail())
"
```

Expected: Data printed for 上证指数, 贵州茅台 quote, and 30-day history.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock investbrief/cn/client.py
git commit -m "feat: add AKShare client with core methods (index, quote, history)"
```

---

### Task 10: Implement cn/client.py analyst + financial methods

**Files:**
- Modify: `investbrief/cn/client.py`

- [ ] **Step 1: Add analyst research report methods**

```python
# ---- 分析师研报 ----

def get_research_reports(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
    """获取个股研报列表。

    Args:
        symbol: 6位股票代码
        limit: 返回数量上限
    """
    try:
        df = ak.stock_research_report_em(symbol=symbol)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.head(limit).iterrows():
            results.append({
                "title": str(row.get("标题", "")),
                "rating": str(row.get("评级", "")),
                "target_price": self._safe_float(row.get("目标价")),
                "institution": str(row.get("机构名称", "")),
                "analyst": str(row.get("分析师", "")),
                "date": str(row.get("发布日期", "")),
            })
        return results
    except Exception as e:
        logger.warning(f"AKShare get_research_reports failed for {symbol}: {e}")
        return []


def get_analyst_rating_summary(self, symbol: str) -> dict[str, Any] | None:
    """聚合研报评级分布 + 平均目标价。

    Returns:
        {"buy": int, "outperform": int, "neutral": int, "underperform": int, "sell": int,
         "avg_target_price": float|None, "total_reports": int}
    """
    reports = self.get_research_reports(symbol, limit=50)
    if not reports:
        return None

    rating_map = {
        "buy": ["买入", "强烈推荐", "推荐"],
        "outperform": ["增持", "优于大市"],
        "neutral": ["中性", "持有", "观望"],
        "underperform": ["减持", "落后大市"],
        "sell": ["卖出"],
    }
    counts = {"buy": 0, "outperform": 0, "neutral": 0, "underperform": 0, "sell": 0}
    target_prices = []

    for r in reports:
        rating = r.get("rating", "")
        matched = False
        for key, aliases in rating_map.items():
            if any(a in rating for a in aliases):
                counts[key] += 1
                matched = True
                break
        if not matched:
            counts["neutral"] += 1
        tp = r.get("target_price")
        if tp and tp > 0:
            target_prices.append(tp)

    return {
        "buy": counts["buy"],
        "outperform": counts["outperform"],
        "neutral": counts["neutral"],
        "underperform": counts["underperform"],
        "sell": counts["sell"],
        "avg_target_price": sum(target_prices) / len(target_prices) if target_prices else None,
        "total_reports": len(reports),
    }
```

- [ ] **Step 2: Add financial indicators method**

```python
# ---- 财务指标 ----

def get_financial_indicators(self, symbol: str) -> dict[str, Any] | None:
    """获取个股财务指标：EPS、ROE、营收增长等。"""
    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol)
        if df is None or df.empty:
            return None
        row = df.iloc[0]  # 最新一期
        return {
            "eps": self._safe_float(row.get("基本每股收益")),
            "roe": self._safe_float(row.get("净资产收益率")),
            "revenue_growth": self._safe_float(row.get("营业收入同比增长率")),
            "profit_growth": self._safe_float(row.get("净利润同比增长率")),
            "gross_margin": self._safe_float(row.get("销售毛利率")),
            "net_margin": self._safe_float(row.get("销售净利率")),
            "debt_ratio": self._safe_float(row.get("资产负债率")),
            "report_date": str(row.get("日期", "")),
        }
    except Exception as e:
        logger.warning(f"AKShare get_financial_indicators failed for {symbol}: {e}")
        return None
```

- [ ] **Step 3: Verify new methods**

```bash
uv run python -c "
from investbrief.cn.client import AKShareClient
c = AKShareClient()
print('=== Rating Summary ===')
print(c.get_analyst_rating_summary('600519'))
print('=== Financial Indicators ===')
print(c.get_financial_indicators('600519'))
"
```

- [ ] **Step 4: Commit**

```bash
git add investbrief/cn/client.py
git commit -m "feat: add AKShare client analyst + financial methods"
```

---

### Task 11: Implement cn/client.py insider + special methods

**Files:**
- Modify: `investbrief/cn/client.py`

- [ ] **Step 1: Add insider trading methods**

```python
# ---- 高管/大股东增减持 ----

def get_insider_trades(self, symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """获取高管增减持记录。"""
    try:
        df = ak.stock_em_ggcg(symbol=symbol)
        if df is None or df.empty:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        results = []
        for _, row in df.iterrows():
            date_str = str(row.get("变动日期", row.get("日期", "")))
            if date_str < cutoff:
                continue
            results.append({
                "name": str(row.get("高管姓名", "")),
                "position": str(row.get("职务", "")),
                "action": str(row.get("变动方向", "")),
                "shares": self._safe_float(row.get("变动股数")),
                "amount": self._safe_float(row.get("变动金额")),
                "date": date_str,
            })
        return results[:10]
    except Exception as e:
        logger.warning(f"AKShare get_insider_trades failed for {symbol}: {e}")
        return []


def get_major_shareholder_trades(self, symbol: str, days: int = 90) -> list[dict[str, Any]]:
    """获取大股东增减持记录。"""
    try:
        df = ak.stock_em_gdxj(symbol=symbol)
        if df is None or df.empty:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        results = []
        for _, row in df.iterrows():
            date_str = str(row.get("日期", ""))
            if date_str < cutoff:
                continue
            results.append({
                "shareholder": str(row.get("股东名称", "")),
                "action": str(row.get("增减持", "")),
                "shares": self._safe_float(row.get("增减持股数")),
                "amount": self._safe_float(row.get("增减持金额")),
                "date": date_str,
            })
        return results[:10]
    except Exception as e:
        logger.warning(f"AKShare get_major_shareholder_trades failed for {symbol}: {e}")
        return []
```

- [ ] **Step 2: Add A-share special data methods**

```python
# ---- A股特色数据 ----

def get_dragon_tiger_list(self, days: int = 5) -> list[dict[str, Any]]:
    """获取近N天龙虎榜数据。"""
    try:
        results = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            try:
                df = ak.stock_lhb_detail_em(date=date)
                if df is None or df.empty:
                    continue
                for _, row in df.head(20).iterrows():
                    results.append({
                        "symbol": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "price": self._safe_float(row.get("收盘价")),
                        "change_pct": self._safe_float(row.get("涨跌幅")),
                        "buy_amount": self._safe_float(row.get("买入额")),
                        "sell_amount": self._safe_float(row.get("卖出额")),
                        "net_buy": self._safe_float(row.get("净额")),
                        "reason": str(row.get("上榜原因", "")),
                        "date": date,
                    })
            except Exception:
                continue
        return results
    except Exception as e:
        logger.warning(f"AKShare get_dragon_tiger_list failed: {e}")
        return []


def get_institutional_research(self, symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """获取机构调研记录。"""
    try:
        df = ak.stock_em_jgdy_tj(symbol=symbol)
        if df is None or df.empty:
            return []
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        results = []
        for _, row in df.head(10).iterrows():
            date_str = str(row.get("调研日期", row.get("日期", "")))
            results.append({
                "institution": str(row.get("机构名称", "")),
                "date": date_str,
                "type": str(row.get("调研形式", "")),
                "researchers": str(row.get("调研人员", "")),
            })
        return results
    except Exception as e:
        logger.warning(f"AKShare get_institutional_research failed for {symbol}: {e}")
        return []
```

- [ ] **Step 3: Add stock news method**

```python
# ---- 新闻 ----

def get_stock_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
    """获取个股相关新闻（东方财富源）。"""
    try:
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.head(limit).iterrows():
            results.append({
                "title": str(row.get("新闻标题", "")),
                "content": str(row.get("新闻内容", "")),
                "url": str(row.get("新闻链接", "")),
                "date": str(row.get("发布时间", "")),
                "source": str(row.get("文章来源", "")),
            })
        return results
    except Exception as e:
        logger.warning(f"AKShare get_stock_news failed for {symbol}: {e}")
        return []
```

- [ ] **Step 4: Verify all methods**

```bash
uv run python -c "
from investbrief.cn.client import AKShareClient
c = AKShareClient()
print('=== Insider Trades ===')
print(c.get_insider_trades('600519'))
print('=== Dragon Tiger ===')
print(c.get_dragon_tiger_list(days=1)[:3])
print('=== Institutional Research ===')
print(c.get_institutional_research('600519'))
print('=== Stock News ===')
print(c.get_stock_news('600519', limit=3))
"
```

- [ ] **Step 5: Commit**

```bash
git add investbrief/cn/client.py
git commit -m "feat: add AKShare client insider, dragon tiger, research, news methods"
```

> **Note:** AKShare 接口名称可能因版本更新而变化。如遇 `AttributeError`，查阅 [AKShare 文档](https://akshare.akfamily.xyz/) 确认最新接口名，并在代码中更新。

---

### Task 12: Implement cn/news.py

**Files:**
- Create: `investbrief/cn/news.py`

- [ ] **Step 1: Create A 股新闻获取模块**

```python
"""A股新闻获取模块。"""

import logging
from typing import Any
from datetime import datetime, timedelta

from .client import AKShareClient

logger = logging.getLogger(__name__)


def fetch_cn_news(tickers: list[str], industries: list[str], limit: int = 20) -> list[dict[str, Any]]:
    """获取 A 股相关新闻。

    优先使用 AKShare 个股新闻，备选使用 Tavily 搜索中文新闻。
    """
    client = AKShareClient()
    all_news = []

    # 1. 获取每个持仓个股的新闻
    seen_titles = set()
    for symbol in tickers:
        stock_news = client.get_stock_news(symbol, limit=5)
        for n in stock_news:
            title = n.get("title", "")
            if title not in seen_titles:
                seen_titles.add(title)
                all_news.append({
                    "title": title,
                    "summary": n.get("content", "")[:200],
                    "url": n.get("url", ""),
                    "date": n.get("date", ""),
                    "source": n.get("source", ""),
                    "symbol": symbol,
                })

    # 2. 按日期排序，取最新的
    all_news.sort(key=lambda x: x.get("date", ""), reverse=True)
    return all_news[:limit]
```

- [ ] **Step 2: Commit**

```bash
git add investbrief/cn/news.py
git commit -m "feat: add A-share news fetching module"
```

---

### Task 13: Implement cn/watchlist.py

**Files:**
- Create: `investbrief/cn/watchlist.py`

- [ ] **Step 1: Create A 股行业关注列表**

```python
"""A股行业关注列表。"""

INDUSTRY_WATCHLISTS: dict[str, list[dict[str, str]]] = {
    "semiconductor": [
        {"symbol": "002049", "name": "紫光国微"},
        {"symbol": "688981", "name": "中芯国际"},
        {"symbol": "603501", "name": "韦尔股份"},
        {"symbol": "300782", "name": "卓胜微"},
        {"symbol": "688012", "name": "中微公司"},
        {"symbol": "002371", "name": "北方华创"},
        {"symbol": "300661", "name": "圣邦股份"},
        {"symbol": "688256", "name": "寒武纪"},
    ],
    "new_energy": [
        {"symbol": "300750", "name": "宁德时代"},
        {"symbol": "002594", "name": "比亚迪"},
        {"symbol": "601012", "name": "隆基绿能"},
        {"symbol": "600438", "name": "通威股份"},
        {"symbol": "002709", "name": "天赐材料"},
        {"symbol": "300014", "name": "亿纬锂能"},
        {"symbol": "600905", "name": "三峡能源"},
    ],
    "consumption": [
        {"symbol": "600519", "name": "贵州茅台"},
        {"symbol": "000858", "name": "五粮液"},
        {"symbol": "000568", "name": "泸州老窖"},
        {"symbol": "600036", "name": "招商银行"},
        {"symbol": "601318", "name": "中国平安"},
        {"symbol": "000651", "name": "格力电器"},
        {"symbol": "600276", "name": "恒瑞医药"},
    ],
    "ai_digital": [
        {"symbol": "002230", "name": "科大讯飞"},
        {"symbol": "688787", "name": "海天瑞声"},
        {"symbol": "603019", "name": "中科曙光"},
        {"symbol": "000977", "name": "浪潮信息"},
        {"symbol": "688111", "name": "金山办公"},
        {"symbol": "300033", "name": "同花顺"},
    ],
}

INDUSTRY_LABELS: dict[str, str] = {
    "semiconductor": "半导体",
    "new_energy": "新能源",
    "consumption": "消费/金融",
    "ai_digital": "AI/数字经济",
}


def get_watchlist_stocks(industries: list[str]) -> list[dict[str, str]]:
    """获取指定行业的关注股票列表。"""
    result = []
    for industry in industries:
        stocks = INDUSTRY_WATCHLISTS.get(industry, [])
        for s in stocks:
            result.append({**s, "industry": industry})
    return result
```

- [ ] **Step 2: Commit**

```bash
git add investbrief/cn/watchlist.py
git commit -m "feat: add A-share industry watchlists"
```

---

### Task 14: Implement cn/calendar.py

**Files:**
- Create: `investbrief/cn/calendar.py`

- [ ] **Step 1: Create A 股经济日历模块**

```python
"""A股经济日历：央行、PMI、CPI、LPR 等重要日期。"""

import logging
from datetime import datetime, timedelta
from calendar import monthcalendar
from typing import Any

logger = logging.getLogger(__name__)

# LPR 公布日：每月 20 日（遇周末顺延至下一个工作日）
# PMI 公布日：每月最后一天或次月 1 日
# CPI/PPI 公布日：次月中旬（约 9-12 日）
# 社融数据：次月中旬
# M2 数据：次月中旬

PERIODIC_EVENTS: list[dict[str, Any]] = [
    {
        "name": "LPR 报价",
        "importance": "high",
        "rule": "monthly_offset",
        "month_offset": 0,
        "day": 20,
    },
    {
        "name": "官方 PMI",
        "importance": "high",
        "rule": "month_end",
        "month_offset": 0,
    },
    {
        "name": "财新 PMI",
        "importance": "medium",
        "rule": "nth_weekday",
        "week": 1,
        "weekday": 2,
        "month_offset": 1,
    },
    {
        "name": "CPI/PPI",
        "importance": "high",
        "rule": "nth_weekday",
        "week": 2,
        "weekday": 4,
        "month_offset": 1,
    },
    {
        "name": "社融/M2 数据",
        "importance": "high",
        "rule": "monthly_offset",
        "month_offset": 1,
        "day": 12,
    },
    {
        "name": "城镇调查失业率",
        "importance": "medium",
        "rule": "monthly_offset",
        "month_offset": 1,
        "day": 15,
    },
]

# 固定日期事件
FIXED_EVENTS: list[dict[str, str]] = [
    {"name": "A股休市：春节", "importance": "high", "note": "农历新年前后，具体日期每年不同"},
    {"name": "A股休市：国庆节", "importance": "high", "date_pattern": "10-01 to 10-07"},
    {"name": "A股休市：劳动节", "importance": "high", "date_pattern": "05-01 to 05-05"},
]


def _nth_weekday_of_month(year: int, month: int, week: int, weekday: int) -> str:
    """计算某年某月第N个周X的日期。weekday: 0=周一, 4=周五。"""
    weeks = monthcalendar(year, month)
    if week <= len(weeks):
        day = weeks[week - 1][weekday]
        if day == 0:
            day = weeks[week][weekday] if week < len(weeks) else weeks[-1][weekday]
        return f"{year}-{month:02d}-{day:02d}"
    return ""


def _adjust_to_weekday(date_str: str) -> str:
    """如果日期落在周末，顺延到下一个周一。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.weekday() == 5:  # Saturday
        dt += timedelta(days=2)
    elif dt.weekday() == 6:  # Sunday
        dt += timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def get_upcoming_events(days_ahead: int = 30) -> list[dict[str, Any]]:
    """获取未来 N 天的 A 股经济事件。"""
    now = datetime.now()
    results = []

    for event in PERIODIC_EVENTS:
        for month_offset in range(0, 3):  # 检查未来 3 个月
            try:
                target_year = now.year
                target_month = now.month + month_offset + event.get("month_offset", 0)
                while target_month > 12:
                    target_month -= 12
                    target_year += 1

                rule = event["rule"]

                if rule == "monthly_offset":
                    day = event.get("day", 15)
                    date_str = f"{target_year}-{target_month:02d}-{day:02d}"
                    date_str = _adjust_to_weekday(date_str)

                elif rule == "nth_weekday":
                    date_str = _nth_weekday_of_month(
                        target_year, target_month,
                        event.get("week", 1), event.get("weekday", 4),
                    )

                elif rule == "month_end":
                    if target_month == 12:
                        next_month = datetime(target_year + 1, 1, 1)
                    else:
                        next_month = datetime(target_year, target_month + 1, 1)
                    last_day = (next_month - timedelta(days=1)).day
                    date_str = f"{target_year}-{target_month:02d}-{last_day:02d}"

                else:
                    continue

                event_date = datetime.strptime(date_str, "%Y-%m-%d")
                delta = (event_date - now).days
                if 0 <= delta <= days_ahead:
                    results.append({
                        "name": event["name"],
                        "date": date_str,
                        "importance": event["importance"],
                        "days_away": delta,
                    })
            except Exception as e:
                logger.warning(f"Failed to calculate date for {event['name']}: {e}")
                continue

    results.sort(key=lambda x: x["date"])
    return results
```

- [ ] **Step 2: Verify**

```bash
uv run python -c "
from investbrief.cn.calendar import get_upcoming_events
events = get_upcoming_events(60)
for e in events:
    print(f\"{e['date']} ({e['days_away']}天后) [{e['importance']}] {e['name']}\")
"
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/cn/calendar.py
git commit -m "feat: add A-share economic calendar (PMI, CPI, LPR, etc.)"
```

---

## Phase 3: CNMarketProvider + Integration

> 实现 CNMarketProvider 并接入 pipeline，端到端可运行。

### Task 15: Implement CNMarketProvider — data methods

**Files:**
- Create: `investbrief/cn/provider.py`

- [ ] **Step 1: Create CNMarketProvider with data fetching**

```python
"""A股市场数据提供者。"""

import logging
from typing import Any

from investbrief.core.provider import MarketProvider
from investbrief.core.charts import generate_stock_chart
from .client import AKShareClient
from .watchlist import get_watchlist_stocks, INDUSTRY_LABELS
from .calendar import get_upcoming_events

logger = logging.getLogger(__name__)

# A 股主要指数代码
INDEX_SYMBOLS: dict[str, str] = {
    "上证指数": "000001",
    "深证成指": "399001",
    "创业板指": "399006",
    "沪深300": "000300",
    "科创50": "000688",
}


class CNMarketProvider(MarketProvider):
    """A股市场数据获取和渲染。"""

    market_code = "cn"
    country_name = "A股市场"
    currency = "¥"
    flag = "🇨🇳"

    def __init__(self):
        self.client = AKShareClient()

    def get_indices(self) -> list[dict[str, Any]]:
        """获取 A 股主要指数行情。"""
        indices = []
        for name, symbol in INDEX_SYMBOLS.items():
            quote = self.client.get_index_quote(symbol)
            if quote:
                quote["name"] = name
                indices.append(quote)
            else:
                indices.append({
                    "symbol": symbol,
                    "name": name,
                    "price": None,
                    "change": None,
                    "change_pct": None,
                })
        return indices

    def get_holdings_data(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """获取持仓个股全部详情。"""
        results = []
        for h in holdings:
            symbol = h.get("symbol", "")
            name = h.get("name", symbol)

            quote = self.client.get_stock_quote(symbol)
            history = self.client.get_stock_history(symbol, days=180)
            rating_summary = self.client.get_analyst_rating_summary(symbol)
            financial = self.client.get_financial_indicators(symbol)
            insider = self.client.get_insider_trades(symbol)
            research = self.client.get_institutional_research(symbol)

            # K 线图
            chart_b64 = None
            if history is not None and not history.empty:
                chart_b64 = generate_stock_chart(name, history, period="6mo")

            # 技术指标（从历史数据计算）
            technicals = self._calc_technical_indicators(history) if history is not None else None

            stock_data = {
                "symbol": symbol,
                "name": name,
                "quote": quote,
                "chart": chart_b64,
                "technicals": technicals,
                "rating_summary": rating_summary,
                "financial": financial,
                "insider_trades": insider,
                "institutional_research": research,
                "research_reports": self.client.get_research_reports(symbol, limit=5),
            }
            results.append(stock_data)

        return results

    def get_recommendations(self, industries: list[str], exclude: list[str] | None = None) -> list[dict[str, Any]]:
        """按行业获取推荐关注个股。筛选研报看多比例 > 50% 的股票。"""
        exclude = exclude or []
        candidates = get_watchlist_stocks(industries)

        results = []
        for stock in candidates:
            symbol = stock["symbol"]
            if symbol in exclude:
                continue

            rating = self.client.get_analyst_rating_summary(symbol)
            if not rating:
                continue

            total = rating.get("total_reports", 0)
            if total == 0:
                continue

            buy_pct = (rating.get("buy", 0) + rating.get("outperform", 0)) / total * 100
            if buy_pct > 50:
                results.append({
                    "symbol": symbol,
                    "name": stock["name"],
                    "industry": stock.get("industry", ""),
                    "industry_label": INDUSTRY_LABELS.get(stock.get("industry", ""), ""),
                    "buy_pct": buy_pct,
                    "rating_summary": rating,
                })

        results.sort(key=lambda x: x["buy_pct"], reverse=True)
        return results[:5]

    def fetch_all(self, holdings: list[dict], industries: list[str]) -> dict[str, Any]:
        """获取 A 股全部数据。"""
        holdings_symbols = [h["symbol"] for h in holdings]

        indices = self.get_indices()
        holdings_data = self.get_holdings_data(holdings)
        recommendations = self.get_recommendations(industries, exclude=holdings_symbols)
        dragon_tiger = self.client.get_dragon_tiger_list(days=3)
        economic_calendar = get_upcoming_events()

        return {
            "indices": indices,
            "holdings": holdings_data,
            "recommendations": recommendations,
            "dragon_tiger": dragon_tiger,
            "economic_calendar": economic_calendar,
        }

    @staticmethod
    def _calc_technical_indicators(df) -> dict[str, Any] | None:
        """从历史数据计算技术指标：RSI(14), MA50, MA200, MACD。"""
        try:
            if df is None or len(df) < 50:
                return None

            close = df["close"]

            # RSI(14)
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, 1e-10)
            rsi = (100 - (100 / (1 + rs))).iloc[-1]

            # MA
            ma50 = close.rolling(50).mean().iloc[-1]
            ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None

            # MACD (12, 26, 9)
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd_line = (ema12 - ema26).iloc[-1]
            signal_line = (ema12 - ema26).ewm(span=9).mean().iloc[-1]
            macd_histogram = macd_line - signal_line

            return {
                "rsi": round(rsi, 2),
                "ma50": round(ma50, 2),
                "ma200": round(ma200, 2) if ma200 else None,
                "macd": round(macd_line, 4),
                "macd_signal": round(signal_line, 4),
                "macd_histogram": round(macd_histogram, 4),
            }
        except Exception as e:
            logger.warning(f"Failed to calculate technical indicators: {e}")
            return None
```

- [ ] **Step 2: Verify data fetching**

```bash
uv run python -c "
from investbrief.cn.provider import CNMarketProvider
p = CNMarketProvider()
print('=== Indices ===')
for i in p.get_indices():
    print(f\"  {i.get('name')}: {i.get('price')} ({i.get('change_pct', 'N/A')}%)\")
print('=== Holdings (600519) ===')
data = p.get_holdings_data([{'symbol': '600519', 'name': '贵州茅台'}])
if data:
    d = data[0]
    print(f\"  Quote: {d.get('quote', {}).get('price')}\")
    print(f\"  Rating: {d.get('rating_summary')}\")
    print(f\"  Financial: {d.get('financial')}\")
"
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/cn/provider.py
git commit -m "feat: add CNMarketProvider with data fetching methods"
```

---

### Task 16: Implement CNMarketProvider — render methods

**Files:**
- Modify: `investbrief/cn/provider.py`

This is the largest implementation task. Add all `render_*` methods that generate HTML matching the existing email template CSS classes.

- [ ] **Step 1: Add `render_section` main method**

Append to `CNMarketProvider` class:

```python
def render_section(self, data: dict[str, Any], config: dict[str, Any]) -> str:
    """渲染 A 股市场 HTML 区块。"""
    parts = []

    # 市场标题
    parts.append(f"""
    <div class="country-header">
        <h2>{self.flag} {self.country_name}</h2>
    </div>
    """)

    # 大盘指数
    indices = data.get("indices", [])
    if indices:
        parts.append(self._render_indices_table(indices, config))

    # 持仓个股
    holdings = data.get("holdings", [])
    if holdings:
        parts.append(self._render_holdings(holdings, config))

    # 龙虎榜
    dragon_tiger = data.get("dragon_tiger", [])
    if dragon_tiger:
        parts.append(self._render_dragon_tiger(dragon_tiger))

    # 经济日历
    economic = data.get("economic_calendar", [])
    if economic:
        parts.append(self._render_economic_calendar(economic))

    # 行业推荐
    recommendations = data.get("recommendations", [])
    if recommendations:
        parts.append(self._render_recommendations(recommendations, config))

    return "\n".join(parts)
```

- [ ] **Step 2: Add `_render_indices_table`**

```python
def _render_indices_table(self, indices: list[dict], config: dict) -> str:
    """渲染指数行情表格。"""
    color_up = config.get("color_up", "#e74c3c")
    color_down = config.get("color_down", "#27ae60")

    rows = ""
    for idx in indices:
        name = idx.get("name", "")
        price = idx.get("price")
        change_pct = idx.get("change_pct")

        price_str = f"{price:.2f}" if price is not None else "N/A"
        if change_pct is not None:
            color = color_up if change_pct >= 0 else color_down
            sign = "+" if change_pct >= 0 else ""
            change_str = f'<span style="color:{color}">{sign}{change_pct:.2f}%</span>'
        else:
            change_str = "N/A"

        rows += f"""
        <div class="metric-card">
            <div class="stock-name">{name}</div>
            <div class="stock-price">¥{price_str}</div>
            <div>{change_str}</div>
        </div>
        """

    return f"""
    <div class="section">
        <h3>大盘指数</h3>
        <div class="metrics-grid">{rows}</div>
    </div>
    """
```

- [ ] **Step 3: Add `_render_holdings` and `_render_stock_card`**

```python
def _render_holdings(self, holdings: list[dict], config: dict) -> str:
    cards = "\n".join(self._render_stock_card(h, config) for h in holdings)
    return f"""
    <div class="section">
        <h3>持仓个股</h3>
        {cards}
    </div>
    """


def _render_stock_card(self, stock: dict, config: dict) -> str:
    """渲染单个 A 股持仓卡片。"""
    color_up = config.get("color_up", "#e74c3c")
    color_down = config.get("color_down", "#27ae60")
    color_neutral = config.get("color_neutral", "#7f8c8d")

    quote = stock.get("quote") or {}
    name = stock.get("name", "")
    symbol = stock.get("symbol", "")
    price = quote.get("price")
    change_pct = quote.get("change_pct")
    market_cap = quote.get("market_cap")
    pe = quote.get("pe")
    turnover = quote.get("turnover_rate")

    # 价格和涨跌
    price_str = f"¥{price:.2f}" if price else "N/A"
    if change_pct is not None:
        price_color = color_up if change_pct >= 0 else color_down
        sign = "+" if change_pct >= 0 else ""
        change_html = f'<span style="color:{price_color}">{sign}{change_pct:.2f}%</span>'
    else:
        change_html = ""

    # 指标行
    metrics = f"""
    <div class="metrics-row">
        <div class="metric"><span class="stock-detail-header">市值</span> {self._format_cap(market_cap) if market_cap else "N/A"}</div>
        <div class="metric"><span class="stock-detail-header">PE</span> {f"{pe:.1f}" if pe else "N/A"}</div>
        <div class="metric"><span class="stock-detail-header">换手率</span> {f"{turnover:.2f}%" if turnover else "N/A"}</div>
    </div>
    """

    # 研报评级分布
    rating_html = ""
    rating_summary = stock.get("rating_summary")
    if rating_summary:
        rating_html = self._render_rating_bars(rating_summary, color_up, color_down)

    # 技术指标
    tech_html = ""
    technicals = stock.get("technicals")
    if technicals:
        tech_html = self._render_technicals(technicals, price, color_up, color_down)

    # 财务指标
    fin_html = ""
    financial = stock.get("financial")
    if financial:
        fin_html = self._render_financials(financial)

    # 高管增减持
    insider_html = ""
    insider = stock.get("insider_trades", [])
    if insider:
        insider_html = self._render_insider_trades(insider, color_up, color_down)

    # 机构调研
    research_html = ""
    inst_research = stock.get("institutional_research", [])
    if inst_research:
        research_html = self._render_institutional_research(inst_research)

    # K 线图
    chart_html = ""
    chart = stock.get("chart")
    if chart:
        chart_html = f'<div style="text-align:center;margin:10px 0"><img src="data:image/png;base64,{chart}" alt="{name}" style="max-width:100%;height:auto"/></div>'

    return f"""
    <div class="card">
        <div class="card-header">
            <span class="stock-name">{name} ({symbol})</span>
            <span class="stock-price">{price_str} {change_html}</span>
        </div>
        <div class="card-body">
            {metrics}
            {chart_html}
            {rating_html}
            {tech_html}
            {fin_html}
            {insider_html}
            {research_html}
        </div>
    </div>
    """
```

- [ ] **Step 4: Add helper render methods**

```python
def _render_rating_bars(self, rating: dict, color_up: str, color_down: str) -> str:
    """渲染研报评级分布条。"""
    total = rating.get("total_reports", 1)
    labels = [
        ("buy", "买入", color_up),
        ("outperform", "增持", "#f39c12"),
        ("neutral", "中性", "#7f8c8d"),
        ("underperform", "减持", "#e67e22"),
        ("sell", "卖出", color_down),
    ]

    bars = ""
    for key, label, color in labels:
        count = rating.get(key, 0)
        pct = count / total * 100
        bars += f'<div class="rating-bar"><span>{label} ({count})</span><div style="background:{color};width:{pct}%"></div></div>'

    avg_target = rating.get("avg_target_price")
    target_str = f" | 平均目标价: ¥{avg_target:.2f}" if avg_target else ""

    return f"""
    <div class="analyst-section">
        <h4>研报评级 ({total}篇{target_str})</h4>
        {bars}
    </div>
    """


def _render_technicals(self, t: dict, price: float | None, color_up: str, color_down: str) -> str:
    """渲染技术指标。"""
    def _signal(val, threshold_up, threshold_down):
        if val is None: return "N/A", "#7f8c8d"
        if val > threshold_up: return f"{val:.2f}", color_up
        if val < threshold_down: return f"{val:.2f}", color_down
        return f"{val:.2f}", "#7f8c8d"

    rsi_str, rsi_color = _signal(t.get("rsi"), 70, 30)
    ma50 = t.get("ma50")
    ma200 = t.get("ma200")
    macd = t.get("macd", 0)

    price_vs_ma50 = ""
    if price and ma50:
        diff = (price - ma50) / ma50 * 100
        color = color_up if diff >= 0 else color_down
        price_vs_ma50 = f'<div class="metric"><span class="stock-detail-header">偏离MA50</span> <span style="color:{color}">{diff:+.1f}%</span></div>'

    return f"""
    <div class="stock-detail">
        <h4>技术指标</h4>
        <div class="metrics-row">
            <div class="metric"><span class="stock-detail-header">RSI(14)</span> <span style="color:{rsi_color}">{rsi_str}</span></div>
            <div class="metric"><span class="stock-detail-header">MA50</span> {f"¥{ma50:.2f}" if ma50 else "N/A"}</div>
            <div class="metric"><span class="stock-detail-header">MA200</span> {f"¥{ma200:.2f}" if ma200 else "N/A"}</div>
            <div class="metric"><span class="stock-detail-header">MACD</span> {f"{macd:.4f}" if macd else "N/A"}</div>
            {price_vs_ma50}
        </div>
    </div>
    """


def _render_financials(self, f: dict) -> str:
    """渲染财务指标。"""
    def _fmt(val, suffix=""):
        return f"{val:.2f}{suffix}" if val is not None else "N/A"

    return f"""
    <div class="fundamental-section">
        <h4>财务指标</h4>
        <div class="metrics-row">
            <div class="metric"><span class="stock-detail-header">EPS</span> {_fmt(f.get("eps"))}</div>
            <div class="metric"><span class="stock-detail-header">ROE</span> {_fmt(f.get("roe"), "%")}</div>
            <div class="metric"><span class="stock-detail-header">营收增长</span> {_fmt(f.get("revenue_growth"), "%")}</div>
            <div class="metric"><span class="stock-detail-header">净利润增长</span> {_fmt(f.get("profit_growth"), "%")}</div>
        </div>
    </div>
    """


def _render_insider_trades(self, trades: list[dict], color_up: str, color_down: str) -> str:
    """渲染高管增减持。"""
    rows = ""
    for t in trades[:5]:
        action = t.get("action", "")
        color = color_up if "增" in action else color_down
        shares = t.get("shares")
        shares_str = f"{abs(shares):,.0f}股" if shares else ""
        rows += f"""
        <div class="upgrade-item">
            <span>{t.get("date", "")}</span>
            <span>{t.get("name", "")}（{t.get("position", "")}）</span>
            <span style="color:{color}">{action} {shares_str}</span>
        </div>
        """

    return f"""
    <div class="insider-section">
        <h4>高管增减持</h4>
        {rows}
    </div>
    """


def _render_institutional_research(self, research: list[dict]) -> str:
    """渲染机构调研。"""
    rows = ""
    for r in research[:5]:
        rows += f"""
        <div class="upgrade-item">
            <span>{r.get("date", "")}</span>
            <span>{r.get("institution", "")}</span>
            <span>{r.get("type", "")}</span>
        </div>
        """

    return f"""
    <div class="institution-section">
        <h4>机构调研（近30天）</h4>
        {rows}
    </div>
    """


def _render_dragon_tiger(self, items: list[dict]) -> str:
    """渲染龙虎榜。"""
    rows = ""
    for item in items[:10]:
        rows += f"""
        <div class="upgrade-item">
            <span>{item.get("name", "")}({item.get("symbol", "")})</span>
            <span>{item.get("reason", "")}</span>
            <span>净买入: {item.get("net_buy", "N/A")}</span>
        </div>
        """

    return f"""
    <div class="section">
        <h3>龙虎榜（近3日）</h3>
        <div class="insider-section">{rows}</div>
    </div>
    """


def _render_economic_calendar(self, events: list[dict]) -> str:
    """渲染经济日历。"""
    rows = ""
    for e in events:
        importance = "🔴" if e.get("importance") == "high" else "🟡"
        rows += f"""
        <div class="upgrade-item">
            <span>{importance} {e.get("date", "")}（{e.get("days_away", "")}天后）</span>
            <span>{e.get("name", "")}</span>
        </div>
        """

    return f"""
    <div class="section">
        <h3>A股经济日历</h3>
        <div class="insider-section">{rows}</div>
    </div>
    """


def _render_recommendations(self, recs: list[dict], config: dict) -> str:
    """渲染行业推荐关注。"""
    color_up = config.get("color_up", "#e74c3c")
    rows = ""
    for r in recs:
        buy_pct = r.get("buy_pct", 0)
        industry_label = r.get("industry_label", r.get("industry", ""))
        rows += f"""
        <div class="recommendation">
            <span class="stock-name">{r.get("name", "")}({r.get("symbol", "")})</span>
            <span class="rec-buy" style="color:{color_up}">看多 {buy_pct:.0f}%</span>
            <span>{industry_label}</span>
        </div>
        """

    return f"""
    <div class="section">
        <h3>推荐关注</h3>
        {rows}
    </div>
    """

@staticmethod
def _format_cap(cap: float | None) -> str:
    """格式化市值。"""
    if not cap:
        return "N/A"
    if cap >= 1e12:
        return f"{cap / 1e12:.2f}万亿"
    if cap >= 1e8:
        return f"{cap / 1e8:.2f}亿"
    return f"{cap / 1e4:.2f}万"
```

- [ ] **Step 5: Verify rendering produces valid HTML**

```bash
uv run python -c "
from investbrief.cn.provider import CNMarketProvider
p = CNMarketProvider()
data = p.fetch_all(
    [{'symbol': '600519', 'name': '贵州茅台'}],
    ['consumption']
)
html = p.render_section(data, {})
print(f'HTML length: {len(html)} chars')
print(html[:500])
"
```

- [ ] **Step 6: Commit**

```bash
git add investbrief/cn/provider.py
git commit -m "feat: add CNMarketProvider HTML rendering methods"
```

---

### Task 17: Update report.py + run.py for CN pipeline

**Files:**
- Modify: `investbrief/report.py`
- Modify: `run.py`

- [ ] **Step 1: Update AI prompts in `run.py` for multi-market**

Add market-specific daily summary prompts. Find the existing `SYSTEM_PROMPT` constant and make it market-aware:

```python
SYSTEM_PROMPTS = {
    "us": SYSTEM_PROMPT,  # 保留现有美股 prompt
    "cn": """你是一位专业的A股市场分析师。请基于以下A股市场数据和新闻，撰写今日A股市场日报总结。

要求：
1. 用中文撰写，风格专业但易读
2. 包含大盘走势分析、持仓个股点评、重要新闻解读
3. 指出值得关注的风险和机会
4. 不要编造具体数字，如有不确定请模糊处理

市场数据：
{context}""",
}
```

Similarly for `NEWS_SUMMARY_PROMPT`, add a CN variant.

- [ ] **Step 2: Update `send_report` function signature**

Ensure `send_report` receives all needed params:

```python
def send_report(report_data: dict, config: dict, recipients: list):
    """渲染并发送报告给指定 recipients。"""
    template = load_template()

    for r in recipients:
        language = r.get("language", "zh-CN")
        lang_config = get_language_config(language)

        html = render_template(template, report_data, language, r)

        if language != "zh-CN":
            html = translate_html(html, language)

        sender = EmailSender()
        success = sender.send(
            to_email=r["email"],
            subject=report_data["subject"],
            html_content=html,
        )
        if success:
            logger.info(f"Report sent to {r['email']}")
        else:
            logger.error(f"Failed to send to {r['email']}")
```

- [ ] **Step 3: Verify `_run_single_market("us", args)` still works**

```bash
uv run run.py --dry-run --market us
```

Expected: Same output as before.

- [ ] **Step 4: Commit**

```bash
git add run.py investbrief/report.py
git commit -m "feat: update pipeline for multi-market support"
```

---

### Task 18: Update config.example.json with CN section + end-to-end test

**Files:**
- Modify: `config.example.json`

- [ ] **Step 1: Add CN market section to config.example.json**

Enable CN and add sample A-share holdings:

```json
{
  "markets": {
    "us": {
      "enabled": true,
      "schedule": { "cron": "0 23 * * 1-5", "timezone": "Asia/Shanghai" }
    },
    "cn": {
      "enabled": true,
      "schedule": { "cron": "0 17 * * 1-5", "timezone": "Asia/Shanghai" }
    }
  },
  "email_service": { "..." : "..." },
  "recipients": [{
    "id": 1,
    "email": "recipient@example.com",
    "name": "Recipient1",
    "active": true,
    "language": "zh-CN",
    "markets": {
      "us": {
        "industries": ["semiconductor_ai"],
        "holdings": [{"symbol": "AMD", "name": "AMD"}],
        "news_count": 10
      },
      "cn": {
        "industries": ["consumption", "new_energy"],
        "holdings": [
          {"symbol": "600519", "name": "贵州茅台"},
          {"symbol": "300750", "name": "宁德时代"}
        ],
        "news_count": 10
      }
    }
  }]
}
```

- [ ] **Step 2: Update your `config.json` with CN section**

Add a `cn` block under `markets` in your personal config with your actual A-share holdings.

- [ ] **Step 3: End-to-end test — dry run CN**

```bash
uv run run.py --dry-run --market cn
```

Expected: JSON output with A-share data (indices, holdings with quotes/ratings/financials, dragon tiger, economic calendar, news).

- [ ] **Step 4: End-to-end test — actual send CN**

```bash
uv run run.py --now --market cn
```

Expected: Email received with A-share briefing including indices, stock cards with charts/ratings/financials/insider/research, dragon tiger, economic calendar, recommendations, news, AI summary.

- [ ] **Step 5: End-to-end test — verify US still works**

```bash
uv run run.py --now --market us
```

Expected: US email works identically to before.

- [ ] **Step 6: Final commit**

```bash
git add config.example.json
git commit -m "feat: add CN market config and complete A-share briefing integration"
```

---

## Plan Self-Review

### Spec Coverage

| Spec Requirement | Task |
|-----------------|------|
| `lib/` → `investbrief/` restructure | Tasks 1-8 |
| `MarketProvider` ABC | Task 1 |
| Move core modules | Task 2 |
| Move US modules | Task 3 |
| USMarketProvider inherits ABC + fetch_all | Task 4 |
| report.py decoupled from providers | Task 5 |
| run.py --market required | Task 6 |
| Config structure migration | Task 7 |
| Phase 1 verification | Task 8 |
| AKShare dependency | Task 9 |
| cn/client.py core methods | Task 9 |
| cn/client.py analyst methods | Task 10 |
| cn/client.py insider + special | Task 11 |
| cn/news.py | Task 12 |
| cn/watchlist.py | Task 13 |
| cn/calendar.py | Task 14 |
| CNMarketProvider data methods | Task 15 |
| CNMarketProvider render methods | Task 16 |
| report.py + run.py CN pipeline | Task 17 |
| Config template + E2E test | Task 18 |

### Placeholder Scan

No TBDs, TODOs, or "implement later" patterns found.

### Type Consistency

- `fetch_all` returns `dict[str, Any]` in both `MarketProvider` ABC and implementations
- `render_section` takes `(data: dict, config: dict) -> str` consistently
- `get_recommendations` takes `(industries: list[str], exclude: list[str]|None) -> list[dict]` consistently
- `AKShareClient` method return types match what `CNMarketProvider` expects

### Known Risks

1. **AKShare interface names may change** — The exact function names (e.g., `stock_zh_a_spot_em`, `stock_research_report_em`) should be verified against the latest AKShare docs during implementation. The plan includes verification steps.
2. **AKShare data column names in Chinese** — The column names used in pandas DataFrame operations (e.g., `df["代码"]`, `df["最新价"]`) must match what AKShare actually returns. Verify during Task 9.
3. **Rate limiting** — AKShare scrapes public websites; calling too many methods too fast may get IP blocked. The current design calls methods sequentially per holding which should be fine for typical use (5-10 holdings).

# A 股简报功能设计

## 概述

为 invest-brief 项目新增 A 股（沪深）市场简报功能，与现有美股简报完全独立运行。数据源使用 AKShare（免费、无需注册、A股覆盖最全），按独立调度触发、独立构建报告、独立发送邮件。

## 数据源选型

| 维度 | AKShare | yfinance (A股) |
|------|---------|---------------|
| 实时行情 | 完整 | 有，但数据稀疏 |
| 历史K线 | 日/周/月/分钟 | 有 |
| 分析师评级/目标价 | 研报列表（可聚合） | 基本没有 |
| 财务指标 | EPS/PE/ROE 全套 | 稀疏 |
| 高管增减持 | 有 | 无 |
| 龙虎榜 | 有（A股特色） | 无 |
| 机构调研 | 有（A股特色） | 无 |
| 费用 | 免费，无需注册 | 免费 |

结论：AKShare 是 A 股数据唯一合理选择，yfinance 不参与 A 股数据获取。

## 项目结构重构

### 现有结构 → 新结构

```
invest-brief/
├── pyproject.toml
├── run.py                          # 入口，--market 必选
├── config.example.json
├── .env.example
├── Dockerfile
├── docker-compose.yml
│
├── investbrief/                    # 主包（原 lib/）
│   ├── __init__.py
│   ├── core/                       # 公共基础
│   │   ├── __init__.py
│   │   ├── provider.py             # MarketProvider 抽象基类
│   │   ├── charts.py               # K线图生成
│   │   ├── mailer.py               # 邮件发送（原 smtp_client）
│   │   ├── guards.py               # AI 输出校验
│   │   └── models.py               # Pydantic 模型
│   │
│   ├── us/                         # 美股
│   │   ├── __init__.py
│   │   ├── provider.py             # USMarketProvider
│   │   ├── clients.py              # YFinance/Finnhub/AV/Tavily
│   │   ├── news.py                 # 新闻获取+评分
│   │   ├── watchlist.py            # 行业关注列表
│   │   ├── calendar.py             # 经济日历
│   │   ├── congress.py             # 议员交易
│   │   └── insider.py              # 内部人交易
│   │
│   ├── cn/                         # A股
│   │   ├── __init__.py
│   │   ├── provider.py             # CNMarketProvider
│   │   ├── client.py               # AKShare 封装
│   │   ├── news.py                 # A股新闻获取（中文源）
│   │   ├── watchlist.py            # A股行业关注列表
│   │   └── calendar.py             # 央行/PMI 等经济日历
│   │
│   └── report.py                   # 模板渲染+翻译+发送
│
├── templates/
│   └── email_base.html
├── logs/
└── docs/
```

### 文件迁移映射

```
lib/api_clients.py           → investbrief/us/clients.py
lib/data_provider.py         → investbrief/us/news.py
lib/market.py                → investbrief/us/provider.py
lib/watchlists.py            → investbrief/us/watchlist.py
lib/economic_calendar.py     → investbrief/us/calendar.py
lib/congressional_tracker.py → investbrief/us/congress.py
lib/insider_tracker.py       → investbrief/us/insider.py
lib/charts.py                → investbrief/core/charts.py
lib/smtp_client.py           → investbrief/core/mailer.py
lib/guards.py                → investbrief/core/guards.py
lib/models.py                → investbrief/core/models.py
lib/send_report.py           → investbrief/report.py
```

## 配置结构

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
      "enabled": true,
      "schedule": {
        "cron": "0 17 * * 1-5",
        "timezone": "Asia/Shanghai"
      }
    }
  },
  "email_service": { "..." : "..." },
  "recipients": [
    {
      "id": 1,
      "email": "user@example.com",
      "name": "User1",
      "active": true,
      "language": "zh-CN",
      "markets": {
        "us": {
          "industries": ["semiconductor_ai"],
          "holdings": [
            {"symbol": "AMD", "name": "AMD"}
          ],
          "news_count": 10
        },
        "cn": {
          "industries": ["new_energy", "semiconductor"],
          "holdings": [
            {"symbol": "600519", "name": "贵州茅台"},
            {"symbol": "000858", "name": "五粮液"}
          ],
          "news_count": 10
        }
      }
    }
  ]
}
```

A 股 symbol 用纯数字代码（如 `600519`），AKShare 通过代码本身区分交易所：
- `6` 开头 = 沪市
- `0`/`3` 开头 = 深市
- `68` 开头 = 科创板

## MarketProvider 抽象基类

```python
class MarketProvider(ABC):
    market_code: str          # "us" / "cn"
    country_name: str         # "美国市场" / "A股市场"
    currency: str             # "$" / "¥"

    @abstractmethod
    def get_indices(self) -> list[dict]

    @abstractmethod
    def get_holdings_data(self, holdings: list[dict]) -> list[dict]

    @abstractmethod
    def get_recommendations(self, industries: list[str], exclude: list[str]) -> list[dict]

    @abstractmethod
    def render_section(self, data: dict, config: dict) -> str
```

## AKShare Client（`investbrief/cn/client.py`）

```python
class AKShareClient:
    # ---- 指数 ----
    def get_index_quote(self, symbol: str) -> dict

    # ---- 个股行情 ----
    def get_stock_quote(self, symbol: str) -> dict

    # ---- 历史K线 ----
    def get_stock_history(self, symbol: str, period: str, days: int) -> pd.DataFrame

    # ---- 分析师研报 ----
    def get_research_reports(self, symbol: str, limit: int = 10) -> list[dict]
    def get_analyst_rating_summary(self, symbol: str) -> dict
        # 聚合研报：买入/增持/中性/减持/卖出 分布 + 平均目标价

    # ---- 财务指标 ----
    def get_financial_indicators(self, symbol: str) -> dict

    # ---- 高管/大股东增减持 ----
    def get_insider_trades(self, symbol: str, days: int = 30) -> list[dict]
    def get_major_shareholder_trades(self, symbol: str, days: int = 90) -> list[dict]

    # ---- A股特色数据 ----
    def get_dragon_tiger_list(self, symbol: str = None, days: int = 5) -> list[dict]
    def get_institutional_research(self, symbol: str, days: int = 30) -> list[dict]

    # ---- 新闻 ----
    def get_stock_news(self, symbol: str, limit: int = 20) -> list[dict]
```

每个方法内部做异常处理和空值兜底，单个接口失败不影响整体。

## CNMarketProvider 展示板块

```
┌─────────────────────────────┐
│ A股市场日报  2026-05-05      │
├─────────────────────────────┤
│ 大盘指数                      │
│ 上证/深成/创业板/沪深300/科创50 │
├─────────────────────────────┤
│ 持仓个股（每个一张卡片）        │
│  · 行情：价格/涨跌/市值/PE/换手  │
│  · K线图                       │
│  · 技术指标：RSI/MA50/MA200/MACD│
│  · 研报评级分布 + 目标价         │
│  · 财务指标：EPS/ROE/营收增长    │
│  · 高管增减持                    │
│  · 机构调研（近30天）            │
├─────────────────────────────┤
│ 龙虎榜（A股特色）               │
│  近5天上榜个股 + 机构/游资席位    │
├─────────────────────────────┤
│ 行业推荐关注                    │
│  按用户关注行业，推荐研报看多个股  │
├─────────────────────────────┤
│ A股新闻 + AI 摘要               │
├─────────────────────────────┤
│ AI 日报总结                     │
└─────────────────────────────┘
```

### 中美简报差异

| 差异点 | 美股 | A股 |
|--------|------|-----|
| 盘前异动 | 有 | 无 |
| 财报日历 | 有 | 有（财报披露日期） |
| 议员交易 | 有 | 无 |
| 内部人交易 | SEC Form 4 | 高管/大股东增减持 |
| 龙虎榜 | 无 | 有（A股特色） |
| 机构调研 | 无 | 有（A股特色） |
| 涨跌色 | 红涨绿跌 | 红涨绿跌（相同） |

## Pipeline 独立调度

### 命令行接口

`--market` 为必选参数：

```bash
uv run run.py --now --market us       # 执行美股
uv run run.py --now --market cn       # 执行A股
uv run run.py --now --market all      # 两个都执行
uv run run.py                         # 调度模式，按 config 独立触发
```

### run_once 流程（单市场）

```python
def run_once(market: str):
    config = load_config()
    recipients = filter_recipients(config["recipients"], market)
    holdings, industries = merge_recipient_settings(recipients, market)
    provider = create_provider(market)

    market_data = provider.fetch_all(holdings, industries)
    news = fetch_news(market, holdings, industries)
    news_summary = summarize_news(news, market)
    daily_summary = generate_daily_summary(market_data, news, market)
    report_data = build_report_data(market, market_data, news, news_summary, daily_summary)

    for recipient in recipients:
        send_report(report_data, recipient, config)
```

### 调度模式

```python
def run_scheduler(config):
    for market, cfg in config["markets"].items():
        if cfg.get("enabled"):
            schedule_job(market, cfg["schedule"])
    loop_forever()
```

两个市场的 cron 独立运行，A股收盘后（~17:00）触发，美股收盘后（~23:00）触发。

## 实施顺序

**先重构验证，再加功能。** 分三个阶段：

### 阶段一：项目结构重构

1. 创建 `investbrief/` 包及子包结构
2. 提取 `MarketProvider` 抽象基类 → `investbrief/core/provider.py`
3. 迁移现有文件到新位置，更新 import 路径
4. 更新 `run.py` 添加 `--market` 参数（必选，`us` 时行为和迁移前一致）
5. 验证：`uv run run.py --now --market us` 输出和迁移前一致

### 阶段二：A 股数据层

1. 实现 `investbrief/cn/client.py`（AKShare 封装）
2. 实现 `investbrief/cn/news.py`（A股新闻获取）
3. 实现 `investbrief/cn/watchlist.py`（A股行业关注列表）
4. 实现 `investbrief/cn/calendar.py`（A股经济日历）
5. 验证：各 client 方法能正确返回数据

### 阶段三：A 股 Provider + 集成

1. 实现 `investbrief/cn/provider.py`（CNMarketProvider）
2. 实现 HTML 渲染（各板块的 render 方法）
3. 更新 `investbrief/report.py` 支持 A 股报告渲染
4. 更新 `run.py` 的 `create_provider` 工厂函数
5. 更新配置模板 `config.example.json`
6. 端到端验证：`uv run run.py --now --market cn`

### 依赖变更

- 新增：`akshare`（pyproject.toml）
- 不移除：`yfinance`（美股仍在用）

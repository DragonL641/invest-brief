# invest-brief

宏观经济日报应用：每个交易日自动抓取 **美股 + A 股** 宏观数据（利率、货币、大类资产、经济日历、新闻），由 Claude 生成核心观点与风险展望，合并渲染为一份双视角 HTML 简报并通过邮件（SMTP）发送。纯后端管道，无 Web 层。

## 功能

- **宏观双视角** — 同一封邮件内并列呈现 US（美债收益率/黄金/美股指数/美元）与 CN（LPR/M2/社融/国债/USDCNY）两侧宏观全景
- **Claude AI 合成** — 自动生成 ① 核心观点（多点详述）与 ⑥ 风险提示与下周关注
- **经济日历** — US（FOMC/CPI/NFP/PCE）、CN（LPR/PMI/CPI/PPI/M2）关键事件
- **新闻聚合** — 多源聚合 + 时间/情绪/相关性/来源质量复合评分
- **多语言** — 支持中文 (zh-CN) 和韩语 (ko-KR)
- **定时调度** — cron 表达式配置，单封合并日报

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 本地运行

```bash
# 1. 安装依赖
uv sync

# 2. 配置
cp config.example.json config.json
cp .env.example .env
# 编辑 config.json 和 .env 填入实际配置

# 3. 立即生成并发送一封合并日报
uv run run.py --now

# 4. 或进入调度模式（按 cron 定时触发）
uv run run.py
```

### 命令行参数

```bash
uv run run.py [--now] [--dry-run] [--skip-summary] [--log-level LEVEL]
```

| 参数 | 说明 |
|------|------|
| `--now` | 立即执行一次（默认进入调度模式）|
| `--dry-run` | 构建合并宏观报告但不发邮件，输出 JSON 到 stdout |
| `--skip-summary` | 跳过 Claude ①⑥（更快，仅结构）|
| `--log-level` | 日志级别：DEBUG / INFO / WARNING / ERROR |
| `--market {us,cn,all}` | **已废弃** — 报告始终为 US+CN 合并单封，参数仅为兼容保留 |

### 测试

```bash
uv run pytest tests/                                 # 全部测试
uv run pytest tests/ -v                              # verbose
```

## 配置说明

### config.json

```json
{
  "markets": {
    "us": {
      "enabled": true,
      "schedule": [
        { "cron": "30 22 * * 1-5", "timezone": "Asia/Shanghai" }
      ]
    },
    "cn": {
      "enabled": true,
      "schedule": [
        { "cron": "0 18 * * 1-5", "timezone": "Asia/Shanghai" }
      ]
    }
  },
  "email_service": {
    "provider": "qq",
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender_email": "YOUR_EMAIL@qq.com",
    "sender_name": "宏观日报"
  },
  "recipients": [
    {
      "email": "recipient@example.com",
      "name": "Recipient1",
      "active": true,
      "language": "zh-CN"
    }
  ]
}
```

`recipients[]` 结构为 `{email, name, active, language}`，无 Web 相关字段。

### .env

```bash
# 必填
ANTHROPIC_API_KEY=                       # Claude API Key（核心观点 + 风险展望）
SMTP_PASSWORD=                           # 邮箱 SMTP 授权码

# 可选（自定义 Claude API 端点与模型）
ANTHROPIC_BASE_URL=                      # 自定义 Anthropic 兼容端点
ANTHROPIC_DEFAULT_SONNET_MODEL=          # 默认 claude-sonnet-4-6；填你的 BASE_URL 支持的模型代号

# 可选（增强美股数据与新闻）
FINNHUB_KEY=                             # Finnhub API Key
ALPHAVANTAGE_KEY=                        # Alpha Vantage API Key
TAVILY_KEY=                              # Tavily 新闻搜索 API Key
```

`ANTHROPIC_AUTH_TOKEN` 会自动别名到 `ANTHROPIC_API_KEY`。macOS 系统代理自动用于 yfinance；akshare（eastmoney）域名走 NO_PROXY。

## 架构

```
run.py                          # 唯一入口：CLI、cron 调度、pipeline 编排

investbrief/
  core/
    provider.py                 # MarketProvider ABC（宏观方法）
    llm.py                      # get_client() 缓存的 Anthropic 客户端 + default_model()
    mailer.py                   # SMTP 邮件发送（带重试）
  us/
    provider.py                 # USMarketProvider — yfinance 宏观（指数/收益率/黄金）
    clients.py                  # YFinanceClient + Finnhub/Alpha Vantage/Tavily
    news.py                     # 美股新闻聚合（带 fallback + 评分）
    calendar.py                 # 美股经济日历（FOMC/CPI/NFP/PCE）
  cn/
    provider.py                 # CNMarketProvider — akshare 宏观（指数/LPR/M2/社融/国债/USDCNY）
    client.py                   # AKShareClient 封装（货币、ETF、指数估值）
    news.py                     # A 股新闻
    calendar.py                 # A 股经济日历（LPR/PMI/CPI/PPI/M2）
  etf/                          # 独立保留的 ETF 分析包（analyzer/engine/indicators/rules.json）
                                # ⚠ 未接入邮件 pipeline，待后续启用
  report.py                     # HTML 模板渲染、宏观标题、多语言（via Claude）

templates/
  email_base.html               # 邮件 HTML 模板
```

**Pipeline 流程：** 加载配置 → 抓取 US 宏观 + CN 宏观 + 新闻 → Claude 生成 ① 核心观点 + ⑥ 风险展望 → `render_section`（US + CN）→ `render_template` 合并 HTML → `send_report` 发送单封邮件。`--dry-run` 时打印 JSON 而非发信。

### 宏观数据来源（已验证）

- **US 利率与资产：** yfinance `^TNX`(10Y) / `^FVX`(5Y) / `^IRX`(13W)；大类资产 `^GSPC` / `^IXIC` / `^DJI` / `^VIX` / `CL=F` / `DX-Y.NYB` / `GC=F`(黄金)。联邦基金目标利率为静态常量（FOMC 后手动更新）。
- **CN 货币与固收：** akshare `macro_china_lpr`（LPR 1Y/5Y）、`macro_china_money_supply`（M2/M1 同比）、`macro_china_shrzgm`（社融）、`bond_china_yield`（CN 10Y，过滤「中债国债收益率曲线」）；汇率 yfinance `USDCNY=X`。
- **中美利差** 由 Claude 基于 US 10Y 与 CN 10Y 数据研判（pipeline 分别透传两项收益率，不做显式减法计算）。

### 机构评级来源（已验证）

> 评级是**结构化数据**（买入/持有/卖出 + 目标价），由数据商按个股聚合后以字段返回；与"机构的宏观/行业观点"（非结构化研报正文）是两类不同数据。本节只覆盖评级。

- **US 个股评级**（`investbrief/us/clients.py`）：
  - **Finnhub** `stock/recommendation`（共识分布 strongBuy/buy/hold/sell/strongSell）+ `stock/price-target`（分析师目标价）。
  - **yfinance** `upgrades_downgrades`（**带 `Firm` 字段、可区分到具体投行**）、`recommendations`（共识分布）、`analyst_price_targets`（目标价）。
  - 覆盖**全部主流投行，含 JPMorgan / Morgan Stanley**（如 AAPL 历史中两家各有数十条记录）。
- **CN 个股评级**（`investbrief/cn/client.py`，`get_research_reports` / `get_analyst_rating_summary`）：
  - **akshare** `stock_research_report_em(symbol)`（底层为东方财富 reportapi）→ 返回 `机构`+`东财评级`+日期，再聚合成评级分布。
  - ⚠ **仅覆盖二线券商**（实测：贵州茅台 759 篇研报，机构为东吴 / 国金 / 华鑫 / 西南 / 东莞 / 民生 / 太平洋 / 中银 / 国信 / 群益等）。
  - ⚠ **头部券商中信证券 / 华泰证券 / 申万宏源 / 中金 / 国泰君安 / 招商等不在免费流** —— 它们将研报与评级数据一并封锁在 Wind / Choice / 同花顺 iFinD 等付费终端。免费渠道对这几家**评级与观点均不可得**。

### 报告结构

`templates/email_base.html`：页头（宏观日报标题）→ ① 核心观点（`.summary-box`，Claude）→ `{{market_sections}}`（US 段 + CN 段，各含 大类资产 / 货币政策 / 经济日历）→ ⑥ 风险提示与下周关注 → 新闻 → 页脚。

## 部署

镜像已发布到 GitHub Container Registry，支持 amd64 和 arm64 架构。仅单个 `scheduler` 服务。

### 生产部署（拉取 GHCR 镜像）

```bash
# 1. 创建部署目录
mkdir invest-brief && cd invest-brief

# 2. 下载 docker-compose 文件
curl -O https://raw.githubusercontent.com/DragonL641/invest-brief/main/docker-compose.prod.yml

# 3. 创建配置文件
cat > config.json << 'EOF'
{ ... 参考 config.example.json ... }
EOF
cat > .env << 'EOF'
ANTHROPIC_API_KEY=your-key
SMTP_PASSWORD=your-password
EOF

# 4. 启动（单个 scheduler 服务）
docker compose -f docker-compose.prod.yml up -d

# 5. 查看日志
docker compose -f docker-compose.prod.yml logs -f
```

**更新到最新版本：**

```bash
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

**手动触发一次邮件（不进入调度模式）：**

```bash
docker compose -f docker-compose.prod.yml run --rm scheduler --now
```

### 本地开发（从源码构建）

```bash
docker compose up --build -d
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言/包管理 | Python 3.12 + uv |
| 美股数据 | yfinance, Finnhub, Alpha Vantage |
| A 股数据 | AKShare |
| 新闻 | Tavily Search |
| AI | Claude API (Anthropic) |
| 图表 | matplotlib |
| 邮件 | SMTP (QQ/Gmail/Outlook/163) |
| 部署 | Docker + GitHub Actions + GHCR |

## License

Private project. All rights reserved.

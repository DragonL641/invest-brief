# invest-brief

个性化每日投资简报，通过邮件推送美股和 A 股市场分析。

## 功能

- **美股** — 指数行情、持仓分析（分析师目标价/EPS/内部人交易/技术指标）、行业新闻摘要
- **A 股** — 指数行情、持仓分析（PE/ROE/机构调研/研报评级/技术指标）、**动态选股推荐**（基于资金流向+换手率+分析师评级的复合评分）
- **Claude AI 摘要** — 自动生成市场总览、持仓诊断、操作建议
- **多语言** — 支持中文 (zh-CN) 和韩语 (ko-KR)
- **定时调度** — cron 表达式配置，支持多市场独立调度

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

# 3. 运行
uv run run.py --market us --now    # 美股立即执行
uv run run.py --market cn --now    # A 股立即执行
uv run run.py --market all --now   # 全部市场
```

### Docker 部署（推荐用于 NAS）

```bash
# 1. 准备配置文件
cp config.example.json config.json
cp .env.example .env
# 编辑配置

# 2. 构建并启动
docker compose up -d

# 3. 查看日志
docker compose logs -f

# 4. 停止
docker compose down
```

## 命令行参数

```bash
uv run run.py --market <us|cn|all> [--now] [--dry-run] [--skip-summary] [--log-level LEVEL]
```

| 参数 | 说明 |
|------|------|
| `--market` | 市场：us（美股）、cn（A 股）、all（全部）|
| `--now` | 立即执行一次（默认进入调度模式）|
| `--dry-run` | 生成报告但不发送邮件，输出 JSON |
| `--skip-summary` | 跳过 Claude API 摘要生成 |
| `--log-level` | 日志级别：DEBUG / INFO / WARNING / ERROR |

## 配置说明

### config.json

```json
{
  "markets": {
    "us": {
      "enabled": true,
      "schedule": { "cron": "0 23 * * 1-5", "timezone": "Asia/Shanghai" }
    },
    "cn": {
      "enabled": true,
      "max_recommendations": 3,
      "schedule": { "cron": "0 17 * * 1-5", "timezone": "Asia/Shanghai" }
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
        },
        "cn": {
          "industries": ["semiconductor", "new_energy"],
          "holdings": [
            {"symbol": "002371", "name": "北方华创"}
          ],
          "news_count": 10
        }
      }
    }
  ]
}
```

**关键字段说明：**

| 字段 | 说明 |
|------|------|
| `markets.<market>.enabled` | 是否启用该市场 |
| `markets.<market>.schedule.cron` | 定时调度 cron 表达式 |
| `markets.cn.max_recommendations` | A 股动态推荐股票数量（默认 3）|
| `email_service.provider` | 邮件服务商：qq / gmail / outlook / 163 |
| `recipients[].language` | 收件人语言：zh-CN / ko-KR |
| `recipients[].markets.us.industries` | 美股关注行业（用于新闻筛选和推荐）|
| `recipients[].markets.us.holdings` | 美股持仓列表 |
| `recipients[].markets.cn.industries` | A 股关注行业 |
| `recipients[].markets.cn.holdings` | A 股持仓列表 |

**A 股行业可选值：** `semiconductor`（半导体）、`new_energy`（新能源）、`consumption`（消费/金融）、`ai_digital`（AI/数字经济）

**美股行业可选值：** `semiconductor_ai`、`aerospace_defense`、`machinery`、`education`

### .env

```bash
# 必填
ANTHROPIC_API_KEY=           # Claude API Key（用于新闻摘要和投资建议）
SMTP_PASSWORD=               # 邮箱 SMTP 授权码

# 可选（增强美股数据）
FINNHUB_KEY=                 # Finnhub API Key
ALPHAVANTAGE_KEY=            # Alpha Vantage API Key
TAVILY_KEY=                  # Tavily 新闻搜索 API Key

# 可选（自定义 Claude API 端点）
ANTHROPIC_BASE_URL=
```

## 架构

```
run.py                      # 入口：CLI、调度、Claude prompts、pipeline 编排
investbrief/
  core/
    provider.py             # MarketProvider ABC
    charts.py               # matplotlib 图表（base64 PNG）
    models.py               # Pydantic 验证模型
    mailer.py               # SMTP 邮件发送
  us/
    provider.py             # USMarketProvider（yfinance）
    clients.py              # yfinance / Finnhub / Alpha Vantage / Tavily
    news.py                 # 美股新闻聚合
    watchlist.py            # 美股行业 watchlist
  cn/
    provider.py             # CNMarketProvider（AKShare）
    client.py               # AKShare 封装
    news.py                 # A 股新闻
    watchlist.py            # 行业配置映射
  report.py                 # HTML 模板渲染、多语言翻译
templates/
  email_base.html           # 邮件 HTML 模板
```

**Pipeline 流程：** 加载配置 → 合并收件人 → 获取市场数据 → 获取新闻 → Claude 摘要 → 生成投资建议 → 渲染 HTML → 发送邮件

**A 股动态选股：** 行业成分股获取 → 资金流入排名 → 粗筛（PE/资金流向/换手率/涨幅复合评分）→ 精筛（分析师买入评级占比）→ Top N 推荐

## Docker 部署详情

Docker 镜像基于 `python:3.12-slim`，使用 `uv` 管理依赖。

**挂载卷：**

| 容器路径 | 说明 |
|---------|------|
| `/app/config.json` | 配置文件（只读）|
| `/app/.env` | 环境变量（只读）|
| `/app/logs` | 日志输出 |
| `/app/reports` | HTML 预览文件 |

**NAS 部署步骤：**

```bash
# 1. 将项目文件上传到 NAS
# 2. 进入项目目录
cd /path/to/invest-brief

# 3. 编辑配置
cp config.example.json config.json
cp .env.example .env
vi config.json .env

# 4. 启动服务
docker compose up -d

# 5. 验证运行
docker compose logs -f
```

**手动触发（不进入调度模式）：**

```bash
docker compose run --rm invest-brief python -m uv run run.py --market us --now
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| 包管理 | uv |
| 美股数据 | yfinance, Finnhub, Alpha Vantage |
| A 股数据 | AKShare |
| 新闻 | Tavily Search |
| AI | Claude API (Anthropic) |
| 图表 | matplotlib |
| 邮件 | SMTP (QQ/Gmail/Outlook/163) |
| 部署 | Docker |

## License

Private project. All rights reserved.

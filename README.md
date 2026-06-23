# invest-brief

个性化每日投资简报平台，支持美股和 A 股市场。通过 **Web Dashboard** 在线浏览 + **邮件推送** 定时发送。

## 功能

- **美股** — 指数行情、持仓分析（分析师目标价/EPS/内部人交易/技术指标）、行业新闻摘要、国会交易追踪、经济日历
- **A 股** — 指数行情、持仓分析（PE/ROE/机构调研/研报评级/技术指标）、**动态选股推荐**（基于资金流向+换手率+分析师评级的复合评分）、龙虎榜、板块行情
- **Claude AI 摘要** — 自动生成市场总览、持仓诊断、操作建议
- **Web Dashboard** — React 前端 + FastAPI 后端，支持 SSE 实时数据流、AI 聊天分析、用户偏好管理
- **多语言** — 支持中文 (zh-CN) 和韩语 (ko-KR)
- **定时调度** — cron 表达式配置，支持多市场独立调度

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Redis（Web Dashboard 需要）

### 本地运行

```bash
# 1. 安装依赖
uv sync

# 2. 配置
cp config.example.json config.json
cp .env.example .env
# 编辑 config.json 和 .env 填入实际配置

# 3. 启动 Redis
redis-server

# 4. 启动 Web API
uv run python run_web.py

# 5. 启动前端（另一个终端）
cd frontend && npm install && npm run dev

# 6. 或者直接运行邮件管道
uv run run.py --market us --now
```

### 命令行参数

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
  "web": {
    "host": "0.0.0.0",
    "port": 8000,
    "secret_key": "CHANGE_ME_TO_A_RANDOM_SECRET"
  },
  "markets": {
    "us": {
      "enabled": true,
      "schedule": [
        { "cron": "30 22 * * 1-5", "timezone": "Asia/Shanghai" },
        { "cron": "0 5 * * 2-6", "timezone": "Asia/Shanghai" }
      ]
    },
    "cn": {
      "enabled": true,
      "max_recommendations": 3,
      "schedule": [
        { "cron": "30 10 * * 1-5", "timezone": "Asia/Shanghai" },
        { "cron": "0 18 * * 1-5", "timezone": "Asia/Shanghai" }
      ]
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
      "password": "bcrypt_hash_here",
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
            {"symbol": "002371", "name": "北方华创"},
            {"symbol": "300750", "name": "宁德时代"}
          ],
          "news_count": 10
        }
      }
    }
  ]
}
```

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

# Redis（Web Dashboard 需要）
REDIS_URL=redis://localhost:6379
```

## 架构

```
run.py                          # 邮件管道入口：CLI、调度、Claude prompts、pipeline 编排
run_web.py                      # Web API 入口：uvicorn 启动 FastAPI

investbrief/
  core/
    provider.py                 # MarketProvider ABC
    charts.py                   # matplotlib 图表（base64 PNG）
    models.py                   # Pydantic 验证模型
    mailer.py                   # SMTP 邮件发送
    guards.py                   # 数据验证守卫
  us/
    provider.py                 # USMarketProvider（yfinance）
    clients.py                  # yfinance / Finnhub / Alpha Vantage / Tavily
    news.py                     # 美股新闻聚合
    calendar.py                 # 美股经济日历
    congress.py                 # 国会交易追踪
    watchlist.py                # 行业 watchlist
    industries.py               # GICS 行业定义
  cn/
    provider.py                 # CNMarketProvider（AKShare）
    client.py                   # AKShare 封装
    news.py                     # A 股新闻
    calendar.py                 # A 股经济日历
    watchlist.py                # 行业配置映射
    industries.py               # 申万一级行业定义
  web/
    app.py                      # FastAPI 应用工厂
    auth.py                     # JWT 认证
    config.py                   # 配置读取 + 原子写入
    deps.py                     # 依赖注入（Redis）
    routers/                    # API 路由（auth, data, stocks, chat, preferences, email）
    services/                   # 业务逻辑（data_fetcher, cache, ai_chat, email_sender）
    models/                     # Pydantic 请求/响应模型
  report.py                     # HTML 模板渲染、多语言翻译

frontend/
  src/
    pages/                      # LoginPage, DashboardPage
    components/                 # React 组件
    api/                        # API 客户端
    types/                      # TypeScript 类型定义

templates/
  email_base.html               # 邮件 HTML 模板
```

**邮件 Pipeline 流程：** 加载配置 → 合并收件人 → 获取市场数据 → 获取新闻 → Claude 摘要 → 生成投资建议 → 渲染 HTML → 发送邮件

**A 股动态选股：** 行业成分股获取 → 资金流入排名 → 粗筛（PE/资金流向/换手率/涨幅复合评分）→ 精筛（分析师买入评级占比）→ Top N 推荐

## 部署

### Docker Compose（推荐）

镜像已发布到 GitHub Container Registry，支持 amd64 和 arm64 架构。

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
REDIS_URL=redis://redis:6379
EOF

# 4. 启动（4 个服务：nginx + api + scheduler + redis）
docker compose -f docker-compose.prod.yml up -d

# 5. 查看日志
docker compose -f docker-compose.prod.yml logs -f
```

**服务说明：**

| 服务 | 镜像 | 说明 |
|------|------|------|
| nginx | `invest-brief-frontend` | React SPA + API 反向代理 |
| api | `invest-brief-api` | FastAPI 后端 |
| scheduler | `invest-brief` | 邮件定时任务 |
| redis | `redis:7-alpine` | 缓存 + 会话存储 |

**更新到最新版本：**

```bash
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

**手动触发一次邮件（不进入调度模式）：**

```bash
docker compose -f docker-compose.prod.yml run --rm scheduler --market us --now
```

### 从源码构建（本地开发）

```bash
docker compose up --build -d
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.12 + FastAPI + uv |
| 前端 | React 19 + TypeScript + Ant Design 6 + Vite |
| 美股数据 | yfinance, Finnhub, Alpha Vantage |
| A 股数据 | AKShare |
| 新闻 | Tavily Search |
| AI | Claude API (Anthropic) |
| 缓存 | Redis |
| 图表 | matplotlib |
| 邮件 | SMTP (QQ/Gmail/Outlook/163) |
| 部署 | Docker + GitHub Actions + GHCR |

## License

Private project. All rights reserved.

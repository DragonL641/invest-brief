# Invest-Brief Web Dashboard Design

## Overview

将 invest-brief 从邮件投递工具升级为 Web 应用，支持：
- 美股/A股市场数据的可视化展示（交互式图表、数据卡片）
- AI 投资助手（全局对话 + 板块嵌入式分析）
- 自选股管理
- 数据缓存与手动刷新
- 邮箱 + 密码认证，用户数据隔离

视觉风格基于 Revolut design token：深色画布、Cobalt Violet 强调色、Inter 字体、无阴影的色块层级系统。

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Nginx     │────▶│  FastAPI    │────▶│   Redis     │
│ (React SPA) │     │  (API)      │     │  (Cache)    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                ┌──────────┴──────────┐
                │  Provider Layer     │
                │  (yfinance/akshare) │
                └──────────┬──────────┘
                           │
                    ┌──────┴──────┐
                    │ Claude API  │
                    │ (AI Chat)   │
                    └─────────────┘
```

4 个 Docker 容器：Nginx（前端 + 反代）、FastAPI（API）、Redis（缓存）、Scheduler（定时刷新）。

## API Design

### Authentication

```
POST /api/auth/login          # 邮箱 + 密码登录，返回 JWT
POST /api/auth/logout         # 登出
GET  /api/auth/me             # 获取当前用户信息
```

邮箱密码在 config.json 的 recipients 中配置（复用现有 `email` 字段作为登录账号）。JWT 中间件校验所有 `/api/*` 请求。

**数据隔离：** 每个用户登录后只能看到自己配置的持仓和关注行业。API 根据当前用户身份过滤数据：
- `GET /api/data/{market}` 只返回该用户 holdings 列表中的股票数据
- 推荐股票基于该用户配置的 industries 生成
- 自选股按用户隔离存储
- 指数、新闻、经济日历等公共数据所有用户共享

### Market Data

```
GET  /api/data/{market}          # 获取缓存的市场数据（公共指数+用户私有持仓）
POST /api/data/{market}/refresh  # 手动触发刷新
GET  /api/status                 # 数据刷新状态、最后更新时间
```

**数据分层缓存：**
- 公共数据（指数、新闻、经济日历）：`market:{market}:public`，所有用户共享
- 用户私有数据（持仓、推荐）：`market:{market}:user:{user_id}:holdings`，按用户隔离
- API 合并公共数据 + 用户私有数据返回给前端

### Watchlist

```
GET    /api/watchlist            # 获取当前用户自选股
POST   /api/watchlist            # 添加自选股 {symbol, name, market}
DELETE /api/watchlist/{id}       # 删除自选股
```

### AI Chat

```
POST /api/chat                   # 全局 AI 对话（SSE streaming）
POST /api/chat/section           # 板块 AI 分析（同步返回）
```

## Cache Design

### Redis Key Schema

```
market:{market}:public           # 公共数据（指数、新闻、日历）JSON，TTL 4h
market:{market}:user:{user_id}:holdings  # 用户私有持仓数据，TTL 4h
market:{market}:user:{user_id}:recs      # 用户推荐股票，TTL 4h
market:{market}:updated_at       # 最后刷新时间戳
user:{user_id}:watchlist         # 用户自选股 JSON，无 TTL
chat:{user_id}:history           # AI 对话历史，TTL 1h，保留 10 轮
```

### Refresh Strategy

- **定时刷新**：Scheduler 容器复用现有 cron 配置，按 schedule 触发 Provider 获取数据写入 Redis
- **手动刷新**：前端点击刷新按钮 → API 清除缓存 → 调 Provider 重新获取 → 写回 Redis → 返回新数据
- **防抖**：同一市场 60 秒内只允许刷新一次

### Cached Data Structure

```json
{
  "updated_at": "2026-05-08T22:30:00+08:00",
  "indices": [
    {"name": "S&P 500", "value": 5234.18, "change": 0.85, "change_pct": 0.016}
  ],
  "holdings": [
    {
      "symbol": "AMD",
      "name": "AMD",
      "price": 178.52,
      "change": 3.24,
      "change_pct": 1.85,
      "info": {"market_cap": "288.5B", "pe": 125.3, "beta": 1.68},
      "targets": {"target_mean": 195.5, "upside": 9.5},
      "technicals": {"rsi": 62.3, "macd_signal": "bullish"},
      "history": [[date, open, high, low, close, volume], ...],
      "chart_b64": "..."
    }
  ],
  "recommendations": [...],
  "news": [...],
  "economic_calendar": [...],
  "earnings_calendar": [...],
  "premarket_movers": [...],
  "dragon_tiger": [...],
  "sector_performance": [...]
}
```

## AI Chatbot Design

### Global Chat (POST /api/chat)

- SSE streaming 响应，前端逐字显示
- System prompt 注入当前 Tab 对应市场的缓存快照数据（约 20-30KB JSON）
- 用户在美股 Tab 对话 → 注入美股数据；A股 Tab → 注入 A股数据
- 对话历史存 Redis，TTL 1h，保留最近 10 轮

### Section Analysis (POST /api/chat/section)

- 前端在具体板块（持仓区、推荐区等）点击"AI 分析"按钮
- 后端取该板块数据 + Claude API 生成详细分析文本，同步返回
- 复用现有 prompt 思路但返回更详细的解读

### Frontend Interaction

- 右下角浮动 AI 机器人图标（FAB 按钮）
- 点击弹出对话框（Drawer 或 Modal），内含对话界面
- 对话框可最小化/关闭
- 支持 Markdown 渲染 AI 回复

## Frontend Design

### Tech Stack

React 18 + Ant Design 5 + TypeScript + Vite + ECharts + react-i18next

### Internationalization (i18n)

支持中文（zh-CN）和韩文（ko-KR），复用现有 recipients 中的 `language` 字段。
- 前端使用 react-i18next，翻译文件按 `zh-CN.json` / `ko-KR.json` 组织
- Header 右侧语言切换 pill 按钮（中/한）
- 用户登录后根据 config 中的 language 设置默认语言，可手动切换
- 后端返回的市场数据（新闻标题摘要）由 Claude API 按用户语言生成

### Pages

**登录页：** 居中卡片，深色背景，邮箱 + 密码输入框 + 登录按钮。

**主页面（美股/A股 Tab 独立，纵向全宽卡片）：**

- Header: Logo | [美股] [A股] Tab | 中/한 语言切换 | 刷新按钮 + 时间 | 用户头像
- 市场概览: 6 个指数卡片均匀填满宽度
- 我的自选股: 纵向全宽详情卡片（见 StockCard）
- 推荐关注: 纵向全宽详情卡片
- 市场新闻: 列表 + 情感标签
- 经济日历: 表格式
- AI Chat FAB: 右下角浮动

### StockCard Component（纵向全宽卡片）

每张股票卡片包含以下信息（与邮件版对齐）：
1. 股票代码 + 公司名称 | 当前价格 + 涨跌幅 + 涨跌额
2. Badge 标注行（MACD金叉/死叉、RSI超买/超卖、目标上行>30%、财报临近、盈利意外等）
3. 关键指标行（市值 | P/E | Beta | 52周范围）
4. 52周价格范围可视化条
5. 分析师目标价 + 上行空间 + 评级分布条（买入/持有/卖出比例）
6. 技术指标（RSI-14、SMA-50、SMA-200、MACD信号）
7. EPS 预估（当前季度实际vs预期、下季预期、上季盈利意外）
8. 内部人交易列表（姓名 + 买入/卖出金额）
9. 评级变动列表（机构 + 评级变化）
10. K 线走势图区域（ECharts 交互式图表占位）
```

### Core Components

| Component | Description |
|-----------|-------------|
| `MarketOverview` | 指数卡片网格，实时价格 + 涨跌幅 |
| `StockCard` | 股票详情卡：价格、技术指标、分析师评级、badge 标签 |
| `InteractiveChart` | ECharts K 线图，支持缩放、1M/3M/6M/1Y 切换 |
| `WatchlistManager` | 自选股增删，与持仓数据联动展示 |
| `NewsList` | 新闻列表，情感标签 + 来源 + 时间 |
| `ChatPanel` | AI 对话面板（浮动触发），Markdown 渲染 |
| `SectionAnalysis` | 板块 AI 分析按钮 + 结果展示 |
| `EconomicCalendar` | 经济日历时间线 |
| `RefreshButton` | 手动刷新 + 状态指示 + 防抖倒计时 |

### Charts Upgrade

用 ECharts 替代 matplotlib base64 PNG：
- 后端返回价格历史数据（JSON 数组）
- 前端渲染交互式 K 线图
- 支持缩放、十字线、技术指标叠加

## Visual Design (Revolut Token Adaptation)

### Dark Theme (Primary)

| Token | Value | Usage |
|-------|-------|-------|
| `canvas-dark` | `#000000` | 页面背景 |
| `surface-elevated` | `#16181a` | 卡片背景 |
| `surface-deep` | `#0a0a0a` | 次级面板背景 |
| `primary` | `#494fdf` | 品牌强调、选中态 |
| `on-dark` | `#ffffff` | 主文本 |
| `on-dark-mute` | `rgba(255,255,255,0.72)` | 次级文本 |
| `stone` | `#8d969e` | 元数据、辅助文本 |
| `hairline-dark` | `rgba(255,255,255,0.12)` | 分割线 |
| `divider-soft` | `rgba(255,255,255,0.06)` | 软分割 |

### Financial Color Extensions

| Role | Value | Usage |
|------|-------|-------|
| `stock-up` | `#ef4444` | 涨（中国惯例红色） |
| `stock-down` | `#22c55e` | 跌（中国惯例绿色） |
| `accent-teal` | `#00a87e` | 正面/买入信号 |
| `accent-warning` | `#ec7e00` | 警告/注意 |
| `accent-danger` | `#e23b4a` | 危险/卖出信号 |

### Typography

| Token | Size | Weight | Usage |
|-------|------|--------|-------|
| `heading-lg` | 32px | 500 | 页面标题 |
| `heading-md` | 24px | 500 | 板块标题 |
| `heading-sm` | 20px | 500 | 卡片标题 |
| `body-md` | 16px | 400 | 正文、数据 |
| `body-md-bold` | 16px | 600 | 强调数据 |
| `body-sm` | 14px | 400 | 辅助信息 |
| `caption` | 13px | 400 | 元数据 |

Font: Inter (替换 Aeonik Pro，开源免费)。

### Shape

| Token | Value | Usage |
|-------|-------|-------|
| `rounded.md` | 12px | 输入框、小卡片 |
| `rounded.lg` | 20px | 数据卡片、面板 |
| `rounded.full` | 9999px | 按钮、badge、Tab |

### Elevation

无阴影。层级通过背景色亮度差表达：
- Level 0: `#000000` 页面背景
- Level 1: `#0a0a0a` 次级面板
- Level 2: `#16181a` 数据卡片
- Level 3: `#494fdf` 强调/选中态

## Backend Structure

```
investbrief/
├── web/                          # NEW: Web application layer
│   ├── __init__.py
│   ├── app.py                    # FastAPI app factory
│   ├── config.py                 # Web-specific config (users, CORS)
│   ├── auth.py                   # JWT auth middleware
│   ├── deps.py                   # Dependency injection (redis, current_user)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py               # Login/logout endpoints
│   │   ├── data.py               # Market data endpoints
│   │   ├── watchlist.py          # Watchlist CRUD
│   │   └── chat.py               # AI chat endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cache.py              # Redis cache layer (get/set/invalidate)
│   │   ├── data_fetcher.py       # Provider orchestration + cache logic
│   │   └── ai_chat.py            # Claude API chat logic
│   └── models/
│       ├── __init__.py
│       └── schemas.py            # Pydantic request/response models
├── core/                         # EXISTING
├── us/                           # EXISTING
├── cn/                           # EXISTING
└── report.py                     # EXISTING (kept for email mode)
```

### Key Design Decisions

1. **Provider 层不修改**：`USMarketProvider` 和 `CNMarketProvider` 的 `fetch_all()` 继续返回 dict，Web 层直接序列化为 JSON
2. **render_section 保留**：邮件模式的 HTML 渲染逻辑不动，Web 模式用新路径
3. **Scheduler 复用**：现有 cron 逻辑不变，改为写 Redis 而非直接渲染邮件
4. **config.json 扩展**：新增 `web` 配置段

### Config Extension

```json
{
  "web": {
    "host": "0.0.0.0",
    "port": 8000,
    "secret_key": "your-jwt-secret"
  },
  "markets": { ... },
  "email_service": { ... },
  "recipients": [
    {
      "id": 1,
      "email": "user@example.com",
      "password": "hashed_password",
      "name": "User1",
      "active": true,
      "language": "zh-CN",
      "markets": {
        "us": {
          "holdings": [{"symbol": "AMD", "name": "AMD"}],
          "industries": ["semiconductor_ai"]
        }
      }
    }
  ]
}
```

用户复用 recipients 配置，`email` 字段作为登录账号，新增 `password` 字段（bcrypt hash）。登录后根据 `id` 隔离数据。

## Deployment

### docker-compose.yml

```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
    depends_on:
      - api

  api:
    build: ./backend
    environment:
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config.json:/app/config.json:ro
      - ./.env:/app/.env:ro
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

  scheduler:
    build: ./backend
    command: python -m investbrief.web.scheduler
    environment:
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config.json:/app/config.json:ro
      - ./.env:/app/.env:ro
    depends_on:
      - redis

volumes:
  redis_data:
```

### External Access

- Cloudflare DNS → 服务器 IP
- Cloudflare 自动 HTTPS
- Nginx 监听 80，Cloudflare SSL 终端

## Success Criteria

1. 用户可通过浏览器访问 Web 应用，用邮箱+密码登录
2. 登录后只看到自己配置的持仓和推荐，数据按用户隔离
3. 可手动触发数据刷新，刷新状态有明确反馈
4. 可管理自选股（增删）
5. AI 助手可基于当前市场数据回答投资相关问题
6. 板块 AI 分析可生成对应板块的解读
7. 交互式 K 线图支持缩放和时间范围切换
8. 支持中文/韩文国际化切换
9. 邮件模式继续可用（不影响现有功能）
10. 单机 Docker 部署，外部可通过域名访问

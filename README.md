# invest-brief

A 股宏观经济日报应用：每个交易日自动抓取 **A 股** 宏观数据 + **外围环境卡**（美联储利率 / 美债 10Y / 标普 500 / USDCNY）+ **黄金**，由 Claude 生成核心观点与风险展望，合并渲染为一份 HTML 简报并通过邮件（SMTP）发送。纯后端管道，无 Web 层。**中文输出**。

- 数据源：**akshare 全覆盖**（A 股指数/货币/外围环境/黄金 SGE）+ FRED（US M2/CPI，用于黄金风险指标）+ Tavily（新闻/卖方观点）。**零 yfinance 依赖**。
- 三类邮件：**宏观日报**（每日广播全体活跃收件人）、可选 **持仓分析**（per-recipient，仅配置 `holdings` 的收件人）、可选 **A 股选股**（每日广播）。

## 功能

- **A 股主 section** — 大类资产 / 货币政策（LPR/M2/社融/CN 10Y） / 经济日历（LPR/PMI/CPI/PPI/M2）/ QVIX 恐慌指数
- **外围环境卡** — 美联储基金利率（静态常量）/ 美债 10Y / 标普 500 / USDCNY，全 akshare，置顶邮件
- **黄金 section** — SGE 金价 + FRED M2/CPI 驱动的风险卡
- **P4 风险模型** — cn/gold 两市场 0-100 市场周期风险评分（5 维度加权，跟踪信号非预测）
- **经济四象限** — cn 的 growth×通胀四象限判定（繁荣/通胀/通缩/滞胀/中性）
- **Claude AI 合成** — ① 核心观点（多点详述）与 ⑥ 风险提示与下周关注
- **卖方机构观点** — Tavily 抓取白名单媒体（Reuters/Bloomberg/FT/WSJ/新浪/华尔街见闻/财新等）+ Claude 综合
- **持仓分析**（可选）— per-recipient 的 CN 个股/ETF/场外基金分析（评级/趋势/资金流/技术面/AI 个股结论）
- **A 股选股**（可选）— 每日量化选股，多因子 + 多风格 profile
- **定时调度** — cron 表达式配置，单封合并日报

## 快速开始

### 环境要求

- Python 3.10+（CI 与 Docker 使用 3.12）
- [uv](https://docs.astral.sh/uv/) 包管理器

### 本地运行

```bash
# 1. 安装依赖
uv sync

# 2. 配置
cp config.example.json config.json
cp .env.example .env
# 编辑 config.json 和 .env 填入实际配置

# 3. 首次部署：全历史回填 CN+黄金 宏观数据（约 10-30 分钟，仅一次）
uv run python scripts/backfill_macro_data.py

# 4. 立即生成并发送一封合并日报
uv run run.py --now

# 5. 或进入调度模式（按 cron 定时触发）
uv run run.py
```

### 命令行参数

```bash
uv run run.py [--now] [--dry-run] [--skip-summary] [--force] [--update] [--only {macro,holdings,picks}] [--log-level LEVEL]
```

| 参数 | 说明 |
|------|------|
| `--now` | 立即执行一次（默认进入调度模式）|
| `--dry-run` | 构建报告但不发邮件，输出 JSON 到 stdout |
| `--skip-summary` | 跳过 Claude ①⑥（更快，仅结构）|
| `--force` | 跳过邮件日级缓存，强制重新生成 macro/picks/holdings |
| `--update` | 仅刷新 SQLite 宏观数据，不渲染不发信（日常补数）|
| `--only {macro,holdings,picks}` | 限制本次只跑单条管线（默认全部）|
| `--log-level` | 日志级别：DEBUG / INFO / WARNING / ERROR |
| `--market {cn,all}` | **已废弃（no-op）** — cn-pivot 后报告恒为 A 股+外围卡+黄金，仅为 CLI 兼容保留 |

### 测试

```bash
uv run pytest tests/                       # 全部测试
uv run pytest tests/ -q -m "not network"   # CI 用：排除真实 API 测试
```

## 配置说明

### config.json

参考 `config.example.json`。关键结构：

```json
{
  "markets": {
    "us": { "enabled": false, "schedule": [...] },   // cn-pivot 后 us 无 provider，enabled 应为 false
    "cn": { "enabled": true,  "schedule": [{"cron": "30 10 * * 1-5", "timezone": "Asia/Shanghai"}] }
  },
  "email_service": { "smtp_server": "smtp.qq.com", "smtp_port": 465, ... },
  "recipients": [
    {
      "email": "recipient@example.com", "name": "Recipient1", "active": true,
      "holdings": [                                       // 可选；配置后额外收到「持仓分析」邮件
        { "symbol": "600519", "market": "cn", "type": "stock" },
        { "symbol": "510300", "market": "cn", "type": "etf" },
        { "symbol": "000001", "market": "cn", "type": "fund" }
      ]
    }
  ]
}
```

> Scheduler 取**第一个 enabled 市场的第一个 cron** 触发。建议把 `us.enabled` 置 `false`，让 cn 的 cron 成为唯一触发源。

`recipients[]` 结构为 `{email, name, active, holdings?}`。可选 `holdings: [{symbol, market, type}]`，**market∈{cn}**，type∈{stock,etf,fund}（fund=CN 场外基金）。

### .env

```bash
# 必填
ANTHROPIC_API_KEY=                       # Claude API Key（核心观点 + 风险展望）
SMTP_PASSWORD=                           # 邮箱 SMTP 授权码
TAVILY_KEY=                              # Tavily 新闻/卖方观点搜索（唯一 news/research key）

# 可选（自定义 Claude API 端点与模型）
ANTHROPIC_BASE_URL=                      # 自定义 Anthropic 兼容端点
ANTHROPIC_DEFAULT_SONNET_MODEL=          # 默认 claude-sonnet-4-5-20250929；填你的 BASE_URL 支持的模型代号
```

`ANTHROPIC_AUTH_TOKEN` 会自动别名到 `ANTHROPIC_API_KEY`。`run.py` 对 eastmoney 域名设置 NO_PROXY（系统代理 SSL 劫持会破坏 CN 行情/历史/资金流）。

## 架构

按**业务域**而非技术层拆分。依赖严格单向：`run.py → pipelines → {market, holdings, risk, regime, mail} → {data, datasources} → core`，`strategies/*.yaml` 为静态配置（由 `core/strategy_loader.py` 加载，非业务域）。域与域之间无横向依赖（如 `market/` 不 import `risk/` 或 `mail/`，只通过 `pipelines/` 协作）。

```
run.py                              # CLI 入口：argparse + 代理/环境引导 + run_once 分发

investbrief/
  core/         config / llm / llm_errors / llm_json / logging / mail_cache /
                scoring / strategy_loader / ta / textfmt / timeutil / indicators
  data/         base / cn_data / gold_data            # SQLite 持久层（指数/宏观时间序列唯一真值源）
  datasources/  akshare / tavily / _common            # 外部 API 适配器（全 akshare + Tavily）
  market/       base.py (MarketProvider ABC)
                __init__.py (MARKET_PROVIDERS 注册表 + create_provider 工厂)
                cn/{provider,calendar,news,indicators}.py
                gold/{provider,indicators}.py
                macro_brief.py (Claude ①⑥ + serialize_macro_context)
                research.py (卖方机构观点：Tavily 抓取 + Claude 综合)
                overseas.py (外围环境卡：美联储利率/美债10Y/标普500/USDCNY，全 akshare)
  holdings/     analyzer / brief / renderer / regime_prompts
                etf/{analyzer,engine,indicators}      # CN ETF 分析（CN-only）
  picks/        brief / cache / data / engine / factors / profiles / renderer / universe  # A 股选股
  risk/         models / config / render              # P4 市场周期风险评分（指标外置到 strategies/risk_indicators.yaml）
  regime/       engine / config / render              # 经济四象限判定（growth×通胀，cn-only）
  strategies/   risk_indicators.yaml / etf_rules.yaml / pick_profiles.yaml
  mail/         sender.py (EmailSender) / render.py (Jinja2)
                templates/{email_base,email_holdings,email_picks}.j2
  pipelines/    macro.py / holdings.py / picks.py / scheduler.py / _send.py
```

**Pipeline 流程（宏观）：** `pipelines/macro.py:run_macro_report` 加载配置 → 刷新 CN+黄金数据（DB-First 快路径，失败回退库内最新值）→ 抓取 CN 宏观 + 外围环境卡 + 新闻 → 计算 P4 风险评分（cn/gold）→ 判定经济四象限（cn）→ Claude ①⑥（注入外围 + cn 宏观 + 风险 + 四象限）→ 卖方机构观点 → 拼装 sections（**外围卡置顶** + A 股主 section + 黄金）→ `mail.render.render_template` → `pipelines._send.send_report` 单封邮件。`--dry-run` 打印 JSON。

**扩展方式：**
- 新增市场 → 在 `market/<mkt>/` 实现 `MarketProvider` 子类 + 在 `market/__init__.py:MARKET_PROVIDERS` 注册一行。
- 新增报告类型 → 加 `pipelines/<name>.py` + 在 `run.py:run_once` 加分发。

### 宏观数据来源（已验证，全 akshare + FRED）

- **外围环境**（`market/overseas.py` + `datasources/akshare.py`）：美联储基金利率 = 静态常量（FOMC 调整时手动更新）；美债 10Y `bond_zh_us_rate`；标普 500 `index_us_stock_sina('.INX')`；USDCNY `forex_spot_em`；CN QVIX `index_option_50etf_qvix` / `index_option_300etf_qvix`。
- **CN 货币与固收**：akshare `macro_china_lpr`（LPR 1Y/5Y）、`macro_china_money_supply`（M2/M1 同比）、`macro_china_shrzgm`（社融）、`bond_china_yield`（CN 10Y，过滤中债国债收益率曲线）。
- **黄金**：akshare SGE 金价 + FRED（US M2/CPI，驱动黄金风险指标）。
- **中美利差** 由 Claude 基于外围卡的「美债 10Y」与 CN section 的「CN 10Y」自行推演（pipeline 分别透传，不做显式减法）。

> akshare frames 列顺序不稳定，取最新值一律按日期/月份列降序排序，不依赖位置。

### 报告结构

`mail/templates/email_base.j2`：页头 → ① 核心观点（`.summary-box`，Claude）→ `{{market_sections}}`（**外围环境卡置顶** + A 股主 section（大类资产/货币政策/经济日历/QVIX + P4 风险卡 + 经济四象限卡）+ 黄金段）→ 🏦 卖方机构观点 → ⑥ 风险提示与下周关注 → 新闻 → 页脚。

持仓邮件（`email_holdings.j2`，独立）与选股邮件（`email_picks.j2`，独立）各有专属模板。

## 部署

镜像已发布到 GitHub Container Registry，支持 amd64 和 arm64。仅单个 `scheduler` 服务。

### 生产部署（拉取 GHCR 镜像）

```bash
# 1. 创建部署目录
mkdir invest-brief && cd invest-brief

# 2. 下载 docker-compose 文件
curl -O https://raw.githubusercontent.com/DragonL641/invest-brief/main/docker-compose.prod.yml

# 3. 创建配置文件（参考 config.example.json）+ .env（ANTHROPIC_API_KEY / SMTP_PASSWORD / TAVILY_KEY）

# 4. 启动（单个 scheduler 服务）
docker compose -f docker-compose.prod.yml up -d

# 5. 查看日志
docker compose -f docker-compose.prod.yml logs -f
```

**更新到最新版本：**

```bash
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

**手动触发一次邮件：**

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
| 语言/包管理 | Python 3.10+（CI 与 Docker 使用 3.12）+ uv |
| A 股/外围/黄金数据 | AKShare |
| US M2/CPI（黄金指标） | FRED |
| 新闻/卖方观点 | Tavily Search |
| AI | Claude API (Anthropic) |
| 邮件 | SMTP (QQ/Gmail/Outlook/163) |
| 部署 | Docker + GitHub Actions + GHCR |

## License

Private project. All rights reserved.

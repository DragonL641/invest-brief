# A股动态选股 — 基于分析师与资金数据的行业推荐

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 去掉 A 股硬编码 watchlist，改为基于 AKShare 行业成分股 + 资金流 + 分析师评级的动态选股。

**Architecture:** 两步筛选 — 先批量接口粗排全行业（5s+15s），再对 Top 10 候选逐个调研报评级（~30s），最终输出 Top 3 推荐。

**Tech Stack:** AKShare (`stock_board_industry_cons_em`, `stock_individual_fund_flow_rank`, `stock_research_report_em`)

---

## 背景

当前 A 股推荐股票来自 `watchlist.py` 的硬编码列表（每个行业 6-8 只），用户希望改为根据分析师判断和资金面数据动态发现行业内最有潜力的股票。

AKShare 的 `stock_institute_recommend`（新浪财经机构评级）已失效（页面改版），因此使用以下替代方案：

- `stock_board_industry_cons_em(board_name)` — 行业全部成分股（含行情/PE/PB/换手率）
- `stock_individual_fund_flow_rank("今日")` — 全量 A 股资金流排名
- `get_analyst_rating_summary(symbol)` — 单只股票研报评级（现有接口）

## 数据流

```
config: industries=["semiconductor", "new_energy", "ai_digital"]
                    ↓
INDUSTRY_SECTOR_NAMES: semiconductor → "半导体", new_energy → "光伏设备"
                    ↓
Step 1 (粗排): stock_board_industry_cons_em("半导体") → 175 只
               stock_individual_fund_flow_rank("今日") → 5286 只
               JOIN on stock code → 175 只 (含资金流数据)
               Filter: PE > 0 and PE < 200
               Score = fund_flow_pct * 0.4 + turnover_rate * 0.2 + price_change_pct * 0.2
               Take Top 10 per industry
                    ↓
Step 2 (精排): For each Top 10 candidate:
               get_analyst_rating_summary(symbol) → buy/outperform/neutral counts
               Filter: buy_pct > 50% (buy+outperform / total)
               Sort by buy_pct DESC
               Take Top N (default 3, configurable via config.max_recommendations)
                    ↓
Output: [{symbol, name, industry, price, change, rating_summary, buy_pct, recommendation_reason}]
```

## 粗排评分公式

对每个行业的所有成分股，计算综合得分：

```
score = normalize(主力净流入占比) * 0.4
      + normalize(换手率) * 0.2
      + normalize(涨跌幅) * 0.2
```

归一化方式：min-max normalization（行业内相对排名），将每个指标归一到 [0, 1]。

过滤条件：
- PE > 0（盈利）且 PE < 200（排除超高估值）
- 主力净流入占比 > 0（资金在流入而非流出）

## 配置变更

`config.json` 新增字段：

```json
{
  "markets": {
    "cn": {
      "max_recommendations": 3,
      "recipients": [...]
    }
  }
}
```

- `max_recommendations`：可选，默认 3，推荐股票数量上限
- `INDUSTRY_SECTOR_NAMES` 保留在代码中（行业 key → AKShare 板块名映射），这是 API 参数不是用户偏好

## 删除的代码

- `investbrief/cn/watchlist.py` 中的 `INDUSTRY_WATCHLISTS` — 删除硬编码股票池
- 保留 `INDUSTRY_LABELS` 和 `INDUSTRY_SECTOR_NAMES`（渲染和 API 调用仍需要）
- `get_watchlist_stocks()` 函数删除

## 新增代码

### `client.py` 新增方法

```python
def get_industry_stocks(self, board_name: str) -> list[dict[str, Any]]:
    """获取行业板块全部成分股。"""
    df = ak.stock_board_industry_cons_em(symbol=board_name)
    # 返回 [{symbol, name, price, change_pct, turnover_rate, pe, pb}, ...]

def get_all_fund_flow(self) -> dict[str, dict]:
    """获取全量个股资金流排名，返回 {symbol: {main_net, main_pct, ...}}"""
    df = ak.stock_individual_fund_flow_rank(indicator="今日")
    # 过滤行业成分股时使用
```

### `provider.py` 修改

`get_recommendations` 方法重写：

```python
def get_recommendations(self, industries, exclude=None):
    # 1. 批量获取所有行业的成分股
    # 2. 批量获取全量资金流
    # 3. JOIN + 粗排评分
    # 4. Top 10 候选精排（调 get_analyst_rating_summary）
    # 5. 返回 Top N
```

## 性能预估

| 步骤 | 接口 | 耗时 |
|------|------|------|
| 粗排：行业成分股 x3 | `stock_board_industry_cons_em` x3 | ~15s |
| 粗排：全量资金流 | `stock_individual_fund_flow_rank` x1 | ~15s |
| 精排：研报评级 | `get_analyst_rating_summary` x 30 (10x3行业) | ~90s |
| **总计** | | **~2 分钟** |

对比当前硬编码方案（~29 分钟），大幅提升。精排阶段可并发（ThreadPoolExecutor）进一步缩短到 ~30s。

## 边界情况

- 非交易日：行业成分股接口返回昨天数据，资金流排名可能无更新。行为与当前一致（展示最近交易日数据）
- 行业板块名不存在：`stock_board_industry_cons_em` 会抛异常，client 内部 try/except 返回空列表
- 精排后不足 3 只（买入评级都不足 50%）：返回实际匹配数量，不强制凑数
- 与持仓重复：保留 exclude 逻辑，排除持仓股票

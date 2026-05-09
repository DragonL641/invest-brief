# StockCard Indicator Enhancement Design

## Background

StockCard 当前存在三个问题：
1. 分析师目标只显示百分比，无法判断样本量是否足够；评级变动与分析师目标割裂展示
2. 技术指标缺少解释，用户不知道参考范围和含义
3. 底部两列布局在 upgrades 移走后不平衡

## Changes

### 1. Analyst Target Section

**卡片内展示：**
- 评级分布条上方标注分析师总数：`20 位分析师`
- 买入/持有/卖出同时显示绝对数和百分比：`Buy 12(60%)  Hold 5(25%)  Sell 3(15%)`
- 右上角添加"查看详情"按钮，触发 Modal

**Modal 内容：**
- 顶部：完整评级分布（绝对数 + 百分比 + 分布条）
- 下方表格：评级变动列表
  - 列：机构 | 评级变动（from -> to）| 目标价 | 日期
  - 数据来源：当前 `stock.upgrades`（yfinance `upgrades_downgrades`）
  - 最多展示 10 条

**删除：** 底部两列布局中的 Upgrades 区域，信息全部移入 Modal。

### 2. Technical Indicator Tooltips

在 Technicals 区域每个指标名称旁添加 info 图标（圆圈 i），hover 显示纯文本 tooltip。

**Technicals tooltip 内容：**

| 指标 | Tooltip |
|------|---------|
| RSI | 范围 0-100。>70 超买（可能回调），<30 超卖（可能反弹）。衡量近期涨跌力度。 |
| SMA 50 | 50 日简单移动均线。价格在其上方为中期上升趋势，下方为下降趋势。 |
| SMA 200 | 200 日简单移动均线。长期趋势分水岭，价格在其上方通常视为牛市。 |
| MACD | MACD 柱状图为正表示短期动量向上（金叉），为负表示向下（死叉）。 |

**EPS tooltip 内容：**

| 指标 | Tooltip |
|------|---------|
| 当季 EPS | 分析师对当前季度每股收益的平均预期。 |
| 下季 EPS | 分析师对下个季度每股收益的平均预期。 |
| Surprise | 上季实际 EPS 与预期的偏差百分比。正值超预期，负值不及预期。 |

实现方式：CSS tooltip 或 title attribute，无需额外依赖。i18n key 存入翻译文件。

### 3. Bottom Layout

从两列改为全宽堆叠，每个区块独占一行：

- **Technicals**：2x2 水平 grid（RSI + SMA50 一行，SMA200 + MACD 一行），每个指标带 info 图标
- **EPS**：单行水平排列（当季 / 下季 / Surprise），每个指标带 info 图标
- **Insider**：全宽列表，展示条数从 3 条增加到 5 条。列：人员(职位) | 操作 | 金额 | 日期

删除 Upgrades 区域（已移入 Modal）。

## Files to Modify

- `frontend/src/components/StockCard.tsx` — 主要改动：布局重构、Modal 组件、Tooltip、评级分布显示
- `frontend/src/i18n/` — 添加 tooltip 和 Modal 相关的翻译 key
- 后端无需改动，数据源已包含 `upgrades`、`recommendations`、`num_analysts` 等所有需要的字段

## Out of Scope

- Badges 区域的 tooltip（后续迭代）
- Modal 内的价格目标可视化图表
- 技术指标当前值的自动解读
- 新增后端数据字段

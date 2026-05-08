# K-Line Chart Enhancements Design

## Context

StockChart currently renders a static 6-month daily candlestick with fixed MA5/10/20 and volume. No period switching, no indicator toggles, no fullscreen. The user wants a feature-complete interactive chart matching typical stock dashboard UX (like TongHuaShun / Xueqiu).

## Scope

1. Period switching: Daily / Weekly / Monthly K-line (front-end aggregation, no API)
2. Time range shortcuts: 1M / 3M / 6M / All
3. MA toggle: click to show/hide individual MA lines
4. RSI / MACD sub-chart indicators (toggle)
5. Fullscreen mode

## Component Structure

```
StockCard
  └── StockChart (history, targetPrice?, symbol)
        ├── ChartToolbar (period, range, MA toggles, RSI/MACD toggles, fullscreen)
        └── ReactECharts (the chart itself)
```

Two new files:
- `StockChart.tsx` — rewritten with internal state management
- `ChartToolbar.tsx` — toolbar with pill buttons

StockCard call signature unchanged: `<StockChart history={stock.history} />`.

## Toolbar Layout

```
[日K] [周K] [月K]  ·  [1M] [3M] [6M] [全部]  ·  MA5 MA10 MA20  ·  RSI MACD  ·  [⛶]
```

Dark pill buttons. Selected: `#494fdf` bg. Unselected: `rgba(255,255,255,0.06)` bg.

MA labels use their line color (MA5 #f59e0b, MA10 #3b82f6, MA20 #a855f7). Unselected state: faded + strikethrough.

## Period Aggregation

Front-end only. Raw data is always daily OHLCV.

**Weekly K:** Group by ISO week (year + week number).
- date = Monday of that week
- open = first day's open
- close = last day's close
- high = max(high) across group
- low = min(low) across group
- volume = sum(volume)

**Monthly K:** Group by year-month.
- date = first day of month
- Same aggregation rules.

Aggregation runs in `useMemo` keyed on `[history, period]`.

## Time Range

Applied after aggregation. Filters data to last N calendar days from the latest date in the dataset.

| Range | Days |
|-------|------|
| 1M    | 30   |
| 3M    | 90   |
| 6M    | 180  |
| 全部   | all  |

Default: 6M. Implemented as dataZoom start/end recalculation, not data slicing.

## MA Toggle

`useState<Set<number>>` default `{5, 10, 20}`. Toggle adds/removes from set. ECharts option regenerated — hidden MA series get empty data arrays.

## RSI / MACD Sub-charts

Two toggle buttons in toolbar. Each adds a grid below the volume chart.

**RSI (14-day):**
- Line chart in a separate grid (height ~60px)
- Horizontal reference lines at 70 (overbought, red dashed) and 30 (oversold, green dashed)
- Y-axis range fixed [0, 100]

**MACD:**
- DIF line + DEA line in one grid
- MACD histogram as bar chart in same grid
- Bar colors: red if positive, green if negative

**Layout with indicators active:**
- K-line: top 38%
- Volume: next 14%
- RSI (if on): next 14%
- MACD (if on): next 14%
- dataZoom slider: bottom 6%

Chart height scales: base 320px, +60px per active indicator.

Calculation:
- RSI: standard 14-period Wilder's smoothing
- MACD: EMA12 - EMA26 for DIF, EMA9 of DIF for DEA, DIF - DEA for histogram

Both computed in `useMemo` from the aggregated data.

## Fullscreen Mode

Toggle via toolbar button or ESC key. Implementation:
- `position: fixed; inset: 0; z-index: 1000` overlay
- Background `#0a0a0a`
- Toolbar rendered inside overlay
- Chart height: `100vh - toolbar height`
- Close button (X) top-right corner

State managed in StockChart via `useState<boolean>`.

## Backend Changes

None. Existing 6-month daily OHLCV data is sufficient for all features.

## i18n

Add keys to zh-CN, ko-KR, en-US:
- `chart.daily`, `chart.weekly`, `chart.monthly`
- `chart.1m`, `chart.3m`, `chart.6m`, `chart.all`
- `chart.rsi`, `chart.macd`
- `chart.fullscreen`, `chart.exitFullscreen`

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/StockChart.tsx` | Rewrite with state management, aggregation, indicators, fullscreen |
| `frontend/src/components/ChartToolbar.tsx` | New file — toolbar component |
| `frontend/src/components/StockCard.tsx` | Pass `symbol` and optional `targetPrice` to StockChart |
| `frontend/src/i18n/zh-CN.json` | Add chart i18n keys |
| `frontend/src/i18n/ko-KR.json` | Add chart i18n keys |

## Verification

1. Period switching: click 日K/周K/月K, chart updates with correct aggregation
2. Time range: click 1M/3M/6M/全部, dataZoom adjusts
3. MA toggle: click MA5 label, line disappears; click again, reappears
4. RSI toggle: enable RSI, sub-chart appears with 14-day RSI line and 70/30 lines
5. MACD toggle: enable MACD, DIF/DEA/histogram appears
6. Fullscreen: click button, chart goes fullscreen; ESC closes
7. All combinations work: weekly K + RSI + fullscreen, monthly K + all MAs, etc.

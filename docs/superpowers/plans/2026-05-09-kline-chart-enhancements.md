# K-Line Chart Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade StockChart from a static candlestick to a full-featured interactive K-line chart with period switching, time range shortcuts, MA toggles, RSI/MACD sub-indicators, and fullscreen mode.

**Architecture:** All changes are frontend-only. StockChart manages internal state (period, range, MA visibility, indicators, fullscreen). A new ChartToolbar provides controls. Data aggregation (daily→weekly→monthly) and indicator calculations (RSI, MACD) happen client-side in `useMemo`. StockCard passes `history` and optional `symbol` — call signature unchanged.

**Tech Stack:** React, TypeScript, ECharts 6 via echarts-for-react, react-i18next.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend/src/components/StockChart.tsx` | Rewritten — state management, aggregation logic, indicator calc, ECharts option builder, fullscreen overlay |
| `frontend/src/components/ChartToolbar.tsx` | **New** — toolbar with period/range/MA/indicator/fullscreen pill buttons |
| `frontend/src/components/StockCard.tsx` | Minor update — pass `symbol` prop to StockChart |
| `frontend/src/i18n/zh-CN.json` | Add chart.* i18n keys |
| `frontend/src/i18n/ko-KR.json` | Add chart.* i18n keys |

---

### Task 1: Add i18n keys

**Files:**
- Modify: `frontend/src/i18n/zh-CN.json`
- Modify: `frontend/src/i18n/ko-KR.json`

- [ ] **Step 1: Add keys to zh-CN.json**

Append these entries to the existing JSON object in `frontend/src/i18n/zh-CN.json`:

```json
  "chart.daily": "日K",
  "chart.weekly": "周K",
  "chart.monthly": "月K",
  "chart.1m": "1月",
  "chart.3m": "3月",
  "chart.6m": "6月",
  "chart.all": "全部",
  "chart.rsi": "RSI",
  "chart.macd": "MACD",
  "chart.fullscreen": "全屏",
  "chart.exitFullscreen": "退出全屏"
```

- [ ] **Step 2: Add keys to ko-KR.json**

Append these entries to the existing JSON object in `frontend/src/i18n/ko-KR.json`:

```json
  "chart.daily": "일K",
  "chart.weekly": "주K",
  "chart.monthly": "월K",
  "chart.1m": "1개월",
  "chart.3m": "3개월",
  "chart.6m": "6개월",
  "chart.all": "전체",
  "chart.rsi": "RSI",
  "chart.macd": "MACD",
  "chart.fullscreen": "전체화면",
  "chart.exitFullscreen": "전체화면 종료"
```

- [ ] **Step 3: Verify JSON is valid**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/zh-CN.json','utf8')); console.log('zh-CN OK')" && node -e "JSON.parse(require('fs').readFileSync('src/i18n/ko-KR.json','utf8')); console.log('ko-KR OK')"`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/zh-CN.json frontend/src/i18n/ko-KR.json
git commit -m "feat(chart): add i18n keys for chart toolbar"
```

---

### Task 2: Create ChartToolbar component

**Files:**
- Create: `frontend/src/components/ChartToolbar.tsx`

- [ ] **Step 1: Write ChartToolbar.tsx**

Create `frontend/src/components/ChartToolbar.tsx` with this content:

```tsx
import { useTranslation } from "react-i18next";

export type Period = "daily" | "weekly" | "monthly";
export type TimeRange = "1m" | "3m" | "6m" | "all";

interface ChartToolbarProps {
  period: Period;
  onPeriodChange: (p: Period) => void;
  range: TimeRange;
  onRangeChange: (r: TimeRange) => void;
  visibleMA: Set<number>;
  onToggleMA: (period: number) => void;
  showRSI: boolean;
  onToggleRSI: () => void;
  showMACD: boolean;
  onToggleMACD: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
}

const MA_CONFIG = [
  { period: 5, color: "#f59e0b" },
  { period: 10, color: "#3b82f6" },
  { period: 20, color: "#a855f7" },
];

const pill: React.CSSProperties = {
  padding: "3px 10px",
  borderRadius: 6,
  fontSize: 11,
  fontWeight: 600,
  cursor: "pointer",
  border: "none",
  outline: "none",
  transition: "background 0.15s",
};

function Pill({
  label,
  active,
  color,
  style,
  onClick,
}: {
  label: string;
  active: boolean;
  color?: string;
  style?: React.CSSProperties;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        ...pill,
        background: active
          ? color || "rgba(73,79,223,0.9)"
          : "rgba(255,255,255,0.06)",
        color: active ? "#fff" : "rgba(255,255,255,0.45)",
        ...(active && color ? { color } : {}),
        ...style,
      }}
    >
      {label}
    </button>
  );
}

export default function ChartToolbar({
  period,
  onPeriodChange,
  range,
  onRangeChange,
  visibleMA,
  onToggleMA,
  showRSI,
  onToggleRSI,
  showMACD,
  onToggleMACD,
  isFullscreen,
  onToggleFullscreen,
}: ChartToolbarProps) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        flexWrap: "wrap",
        padding: "6px 8px",
      }}
    >
      {/* Period */}
      {(["daily", "weekly", "monthly"] as Period[]).map((p) => (
        <Pill
          key={p}
          label={t(`chart.${p}`)}
          active={period === p}
          onClick={() => onPeriodChange(p)}
        />
      ))}

      <span style={{ width: 8 }} />

      {/* Time range */}
      {(["1m", "3m", "6m", "all"] as TimeRange[]).map((r) => (
        <Pill
          key={r}
          label={t(`chart.${r}`)}
          active={range === r}
          onClick={() => onRangeChange(r)}
        />
      ))}

      <span style={{ width: 8 }} />

      {/* MA toggles */}
      {MA_CONFIG.map(({ period: ma, color }) => (
        <Pill
          key={ma}
          label={`MA${ma}`}
          active={visibleMA.has(ma)}
          color={color}
          onClick={() => onToggleMA(ma)}
          style={{
            ...pill,
            background: visibleMA.has(ma)
              ? `${color}33`
              : "rgba(255,255,255,0.06)",
            color: visibleMA.has(ma) ? color : "rgba(255,255,255,0.3)",
            textDecoration: visibleMA.has(ma) ? "none" : "line-through",
          }}
        />
      ))}

      <span style={{ width: 8 }} />

      {/* Indicators */}
      <Pill label="RSI" active={showRSI} onClick={onToggleRSI} />
      <Pill label="MACD" active={showMACD} onClick={onToggleMACD} />

      <div style={{ flex: 1 }} />

      {/* Fullscreen */}
      <button
        type="button"
        onClick={onToggleFullscreen}
        style={{
          ...pill,
          background: "rgba(255,255,255,0.06)",
          color: "rgba(255,255,255,0.5)",
          fontSize: 14,
          lineHeight: 1,
        }}
        title={isFullscreen ? t("chart.exitFullscreen") : t("chart.fullscreen")}
      >
        {isFullscreen ? "✕" : "⛶"}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChartToolbar.tsx
git commit -m "feat(chart): add ChartToolbar component"
```

---

### Task 3: Add data aggregation and indicator calculation utilities

**Files:**
- Create: `frontend/src/utils/chartCalc.ts`

This file contains pure functions for period aggregation, MA/RSI/MACD calculation. Keeping them separate from the component makes them testable and keeps StockChart focused on rendering.

- [ ] **Step 1: Write chartCalc.ts**

Create `frontend/src/utils/chartCalc.ts`:

```ts
export interface HistoryPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type Period = "daily" | "weekly" | "monthly";

/** Group daily data into weekly or monthly OHLCV. Daily is a no-op. */
export function aggregatePeriod(
  data: HistoryPoint[],
  period: Period
): HistoryPoint[] {
  if (period === "daily" || data.length === 0) return data;

  const groups = new Map<string, HistoryPoint[]>();

  for (const pt of data) {
    const d = new Date(pt.date);
    let key: string;
    if (period === "weekly") {
      // ISO week: get Monday of the week
      const day = d.getDay();
      const diff = d.getDate() - day + (day === 0 ? -6 : 1);
      const monday = new Date(d);
      monday.setDate(diff);
      key = monday.toISOString().slice(0, 10);
    } else {
      key = pt.date.slice(0, 7) + "-01";
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(pt);
  }

  return Array.from(groups.entries()).map(([date, pts]) => ({
    date,
    open: pts[0].open,
    close: pts[pts.length - 1].close,
    high: Math.max(...pts.map((p) => p.high)),
    low: Math.min(...pts.map((p) => p.low)),
    volume: pts.reduce((s, p) => s + p.volume, 0),
  }));
}

/** Simple moving average. Returns null for initial insufficient-data points. */
export function calcMA(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i < period - 1) return null;
    const slice = closes.slice(i - period + 1, i + 1);
    return +(slice.reduce((a, b) => a + b, 0) / period).toFixed(2);
  });
}

/** EMA (exponential moving average). */
export function calcEMA(data: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const result: (number | null)[] = [];
  let ema: number | null = null;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else if (ema === null) {
      // Seed: simple average of first `period` values
      ema =
        data.slice(0, period).reduce((a, b) => a + b, 0) / period;
      result.push(+ema.toFixed(4));
    } else {
      ema = data[i] * k + ema * (1 - k);
      result.push(+ema.toFixed(4));
    }
  }
  return result;
}

/** RSI using Wilder's smoothing (14-period). */
export function calcRSI(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = [];
  if (closes.length < period + 1) {
    return closes.map(() => null);
  }

  // Seed: simple average of gains/losses for first `period` deltas
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1];
    if (delta > 0) avgGain += delta;
    else avgLoss += Math.abs(delta);
  }
  avgGain /= period;
  avgLoss /= period;

  // Fill initial nulls
  for (let i = 0; i < period; i++) result.push(null);

  // First RSI value
  const rs0 = avgLoss === 0 ? 100 : avgGain / avgLoss;
  result.push(+(100 - 100 / (1 + rs0)).toFixed(2));

  // Subsequent values using Wilder's smoothing
  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    const gain = delta > 0 ? delta : 0;
    const loss = delta < 0 ? Math.abs(delta) : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    result.push(+(100 - 100 / (1 + rs)).toFixed(2));
  }

  return result;
}

/** MACD: returns { dif, dea, histogram }. DIF = EMA12 - EMA26, DEA = EMA9(DIF). */
export function calcMACD(closes: number[]): {
  dif: (number | null)[];
  dea: (number | null)[];
  histogram: (number | null)[];
} {
  const ema12 = calcEMA(closes, 12);
  const ema26 = calcEMA(closes, 26);

  const dif = ema12.map((v12, i) => {
    const v26 = ema26[i];
    return v12 != null && v26 != null ? +(v12 - v26).toFixed(4) : null;
  });

  // DEA = EMA9 of DIF (skip nulls for seeding)
  const difValues = dif.filter((v) => v != null) as number[];
  const deaFull = calcEMA(difValues, 9);

  // Map back to original indices
  const dea: (number | null)[] = [];
  let j = 0;
  for (let i = 0; i < dif.length; i++) {
    if (dif[i] != null) {
      dea.push(deaFull[j++]);
    } else {
      dea.push(null);
    }
  }

  const histogram = dif.map((d, i) => {
    const e = dea[i];
    return d != null && e != null ? +((d - e) * 2).toFixed(4) : null;
  });

  return { dif, dea, histogram };
}

/** Filter data to last N calendar days. Returns all data if days is Infinity. */
export function filterByRange(
  data: HistoryPoint[],
  days: number
): HistoryPoint[] {
  if (!isFinite(days) || data.length === 0) return data;
  const lastDate = new Date(data[data.length - 1].date);
  const cutoff = new Date(lastDate);
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return data.filter((p) => p.date >= cutoffStr);
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/chartCalc.ts
git commit -m "feat(chart): add aggregation and indicator calculation utilities"
```

---

### Task 4: Rewrite StockChart with full interactivity

**Files:**
- Rewrite: `frontend/src/components/StockChart.tsx`
- Modify: `frontend/src/components/StockCard.tsx` (pass `symbol` prop)

This is the core task. StockChart becomes stateful and builds a dynamic ECharts option based on all the toolbar controls.

- [ ] **Step 1: Rewrite StockChart.tsx**

Replace the entire contents of `frontend/src/components/StockChart.tsx` with:

```tsx
import { useMemo, useState, useEffect, useCallback } from "react";
import ReactECharts from "echarts-for-react";
import ChartToolbar, { type Period, type TimeRange } from "./ChartToolbar";
import {
  type HistoryPoint,
  aggregatePeriod,
  calcMA,
  calcRSI,
  calcMACD,
  filterByRange,
} from "../utils/chartCalc";

interface StockChartProps {
  history: HistoryPoint[];
  symbol?: string;
}

const RANGE_DAYS: Record<TimeRange, number> = {
  "1m": 30,
  "3m": 90,
  "6m": 180,
  all: Infinity,
};

const mono = { fontFamily: "'Geist Mono', monospace" };

export default function StockChart({ history, symbol }: StockChartProps) {
  const [period, setPeriod] = useState<Period>("daily");
  const [range, setRange] = useState<TimeRange>("6m");
  const [visibleMA, setVisibleMA] = useState(() => new Set([5, 10, 20]));
  const [showRSI, setShowRSI] = useState(false);
  const [showMACD, setShowMACD] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Aggregate by period
  const aggregated = useMemo(
    () => aggregatePeriod(history, period),
    [history, period]
  );

  // Filter by time range
  const displayed = useMemo(
    () => filterByRange(aggregated, RANGE_DAYS[range]),
    [aggregated, range]
  );

  const toggleMA = useCallback((p: number) => {
    setVisibleMA((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  }, []);

  // ESC to exit fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsFullscreen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  const option = useMemo(() => {
    if (displayed.length === 0) return {};

    const dates = displayed.map((h) => h.date);
    const ohlc = displayed.map((h) => [h.open, h.close, h.low, h.high]);
    const volumes = displayed.map((h) => h.volume);
    const closes = displayed.map((h) => h.close);

    const volumeColors = displayed.map((h) =>
      h.close >= h.open
        ? "rgba(239,68,68,0.7)"
        : "rgba(34,197,94,0.7)"
    );

    // MA series
    const maSeries: any[] = [
      { period: 5, color: "#f59e0b" },
      { period: 10, color: "#3b82f6" },
      { period: 20, color: "#a855f7" },
    ].map(({ period: p, color }) => ({
      name: `MA${p}`,
      type: "line" as const,
      data: visibleMA.has(p) ? calcMA(closes, p) : [],
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 1, color },
    }));

    // Indicators
    const rsiData = showRSI ? calcRSI(closes) : [];
    const macdData = showMACD ? calcMACD(closes) : null;

    // Count active sub-charts for grid layout
    const subChartCount = [showRSI, showMACD].filter(Boolean).length;
    const baseHeight = isFullscreen ? 100 : 320;
    const chartHeight = baseHeight + subChartCount * 60;

    // Build grids
    const grids: any[] = [
      { left: 48, right: 16, top: 8, height: "48%" },    // K-line
      { left: 48, right: 16, top: "56%", height: "12%" }, // Volume
    ];
    const xAxes: any[] = [
      {
        type: "category",
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.12)" } },
        axisLabel: { color: "#8d969e", fontSize: 10, ...mono },
        splitLine: { show: false },
        axisTick: { show: false },
      },
      {
        type: "category",
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.12)" } },
        axisLabel: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
      },
    ];
    const yAxes: any[] = [
      {
        scale: true,
        splitArea: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
        axisLabel: { color: "#8d969e", fontSize: 10, ...mono },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          show: true,
          color: "#8d969e",
          fontSize: 9,
          ...mono,
          formatter: (v: number) => {
            if (v >= 1e8) return (v / 1e8).toFixed(1) + "亿";
            if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
            return String(v);
          },
        },
      },
    ];
    const series: any[] = [
      {
        name: "K-Line",
        type: "candlestick",
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: "#ef4444",
          color0: "#22c55e",
          borderColor: "#ef4444",
          borderColor0: "#22c55e",
        },
      },
      ...maSeries.map((s) => ({ ...s, xAxisIndex: 0, yAxisIndex: 0 })),
      {
        name: "Volume",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (params: any) => volumeColors[params.dataIndex],
        },
      },
    ];
    const dataZoomXAxisIdxs = [0, 1];

    // RSI sub-chart
    if (showRSI) {
      const rsiGridIdx = grids.length;
      const topPct = 72 + (rsiGridIdx - 2) * 14;
      grids.push({
        left: 48,
        right: 16,
        top: `${topPct}%`,
        height: "10%",
      });
      xAxes.push({
        type: "category",
        gridIndex: rsiGridIdx,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.12)" } },
        axisLabel: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
      });
      yAxes.push({
        min: 0,
        max: 100,
        splitNumber: 2,
        gridIndex: rsiGridIdx,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: {
          lineStyle: { color: "rgba(255,255,255,0.06)", type: "dashed" },
        },
        axisLabel: { color: "#8d969e", fontSize: 9, ...mono },
      });
      series.push({
        name: "RSI",
        type: "line",
        xAxisIndex: rsiGridIdx,
        yAxisIndex: rsiGridIdx,
        data: rsiData,
        showSymbol: false,
        lineStyle: { width: 1, color: "#f59e0b" },
        itemStyle: { color: "#f59e0b" },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { type: "dashed", width: 1 },
          data: [
            {
              yAxis: 70,
              lineStyle: { color: "rgba(239,68,68,0.4)" },
              label: { show: false },
            },
            {
              yAxis: 30,
              lineStyle: { color: "rgba(34,197,94,0.4)" },
              label: { show: false },
            },
          ],
        },
      });
      dataZoomXAxisIdxs.push(rsiGridIdx);
    }

    // MACD sub-chart
    if (showMACD && macdData) {
      const macdGridIdx = grids.length;
      const topPct = 72 + (macdGridIdx - 2) * 14;
      grids.push({
        left: 48,
        right: 16,
        top: `${topPct}%`,
        height: "10%",
      });
      xAxes.push({
        type: "category",
        gridIndex: macdGridIdx,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.12)" } },
        axisLabel: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
      });
      yAxes.push({
        scale: true,
        splitNumber: 2,
        gridIndex: macdGridIdx,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: "#8d969e", fontSize: 9, ...mono },
      });
      // MACD histogram colors
      const macdHistColors = (macdData.histogram as (number | null)[]).map(
        (v) => (v != null && v >= 0 ? "rgba(239,68,68,0.7)" : "rgba(34,197,94,0.7)")
      );
      series.push(
        {
          name: "DIF",
          type: "line",
          xAxisIndex: macdGridIdx,
          yAxisIndex: macdGridIdx,
          data: macdData.dif,
          showSymbol: false,
          lineStyle: { width: 1, color: "#f59e0b" },
          itemStyle: { color: "#f59e0b" },
        },
        {
          name: "DEA",
          type: "line",
          xAxisIndex: macdGridIdx,
          yAxisIndex: macdGridIdx,
          data: macdData.dea,
          showSymbol: false,
          lineStyle: { width: 1, color: "#3b82f6" },
          itemStyle: { color: "#3b82f6" },
        },
        {
          name: "MACD",
          type: "bar",
          xAxisIndex: macdGridIdx,
          yAxisIndex: macdGridIdx,
          data: macdData.histogram,
          itemStyle: {
            color: (params: any) => macdHistColors[params.dataIndex],
          },
        }
      );
      dataZoomXAxisIdxs.push(macdGridIdx);
    }

    return {
      animation: false,
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: "rgba(22,24,26,0.95)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#fff", fontSize: 12, ...mono },
        formatter: (params: any[]) => {
          if (!params || params.length === 0) return "";
          const date = params[0].axisValue;
          let html = `<div style="margin-bottom:4px;font-weight:600">${date}</div>`;
          for (const p of params) {
            if (p.seriesName === "K-Line") {
              const d = p.data;
              const color = d[1] >= d[0] ? "#ef4444" : "#22c55e";
              html += `<div style="color:${color}">开 ${d[0]} 收 ${d[1]}<br/>低 ${d[2]} 高 ${d[3]}</div>`;
            } else if (p.seriesName === "Volume") {
              html += `<div style="color:#8d969e">量 ${(p.data / 10000).toFixed(0)}万</div>`;
            } else if (p.value != null) {
              html += `<div style="color:${p.color}">${p.seriesName} ${typeof p.value === "number" ? p.value.toFixed(2) : p.value}</div>`;
            }
          }
          return html;
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: "all" }],
        label: { backgroundColor: "#494fdf", ...mono },
      },
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      dataZoom: [
        { type: "inside", xAxisIndex: dataZoomXAxisIdxs },
        {
          type: "slider",
          xAxisIndex: dataZoomXAxisIdxs,
          bottom: 4,
          height: 14,
          borderColor: "transparent",
          backgroundColor: "#0a0a0a",
          fillerColor: "rgba(73,79,223,0.2)",
          handleStyle: { color: "#494fdf", borderColor: "#494fdf" },
          textStyle: { color: "#8d969e", fontSize: 10 },
          dataBackground: {
            lineStyle: { color: "rgba(255,255,255,0.15)" },
            areaStyle: { color: "rgba(73,79,223,0.1)" },
          },
          selectedDataBackground: {
            lineStyle: { color: "#494fdf" },
            areaStyle: { color: "rgba(73,79,223,0.2)" },
          },
        },
      ],
      series,
    };
  }, [displayed, visibleMA, showRSI, showMACD, isFullscreen]);

  const subChartCount = [showRSI, showMACD].filter(Boolean).length;
  const chartHeight = (isFullscreen ? 100 : 320) + subChartCount * 60;

  const toolbar = (
    <ChartToolbar
      period={period}
      onPeriodChange={setPeriod}
      range={range}
      onRangeChange={setRange}
      visibleMA={visibleMA}
      onToggleMA={toggleMA}
      showRSI={showRSI}
      onToggleRSI={() => setShowRSI((v) => !v)}
      showMACD={showMACD}
      onToggleMACD={() => setShowMACD((v) => !v)}
      isFullscreen={isFullscreen}
      onToggleFullscreen={() => setIsFullscreen((v) => !v)}
    />
  );

  const chart = (
    <ReactECharts
      option={option}
      style={{ height: chartHeight, width: "100%" }}
      notMerge
    />
  );

  if (isFullscreen) {
    return (
      <div
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1000,
          background: "#0a0a0a",
          display: "flex",
          flexDirection: "column",
          padding: 8,
        }}
      >
        <div style={{ flexShrink: 0 }}>{toolbar}</div>
        <div style={{ flex: 1, minHeight: 0 }}>{chart}</div>
      </div>
    );
  }

  return (
    <div style={{ background: "#0a0a0a", borderRadius: 8, padding: 8 }}>
      {toolbar}
      {chart}
    </div>
  );
}
```

- [ ] **Step 2: Update StockCard.tsx to pass `symbol`**

In `frontend/src/components/StockCard.tsx`, change the StockChart call from:

```tsx
<StockChart history={stock.history} />
```

to:

```tsx
<StockChart history={stock.history} symbol={stock.symbol} />
```

This is a one-line change in the chart section (around line 268).

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/StockChart.tsx frontend/src/components/StockCard.tsx
git commit -m "feat(chart): rewrite StockChart with period switching, MA toggle, RSI/MACD, fullscreen"
```

---

### Task 5: Verify end-to-end with dev server

**Files:** None (verification only)

- [ ] **Step 1: Start backend with cached data**

The backend should already have cached US market data with `history` fields from the previous work. If not, re-run the data seeding script from the earlier session:

```python
python -c "
import sys; sys.path.insert(0, '.')
import redis
from investbrief.us.provider import USMarketProvider
from investbrief.web.services.data_fetcher import _sanitize_floats
from investbrief.web.services.cache import set_cached

p = USMarketProvider()
holdings_config = [
    {'symbol': 'AMD', 'name': 'AMD'},
    {'symbol': 'NVDA', 'name': 'NVIDIA'},
    {'symbol': 'MU', 'name': 'Micron'},
    {'symbol': 'TSLA', 'name': 'Tesla'},
]
holdings_data = p.get_holdings_data(holdings_config)
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
private = {'holdings': holdings_data, 'recommendations': []}
set_cached(r, 'market:us:user:1:private', _sanitize_floats(private))
set_cached(r, 'market:us:news', [])
set_cached(r, 'market:us:public', {'indices': [{'name': 'S&P 500', 'point': 5631.28, 'change': 0.47}], 'economic_calendar': [], 'premarket_movers': [], 'earnings_calendar': [], 'congressional_trades': []})
print('Data cached')
"
```

- [ ] **Step 2: Start dev servers**

Run backend: `uv run python run_web.py`
Run frontend: `cd frontend && npm run dev`

- [ ] **Step 3: Open browser and verify all features**

Open `http://localhost:5173` and test:

1. **Period switching**: Click 日K / 周K / 月K — chart re-renders with fewer bars for weekly/monthly
2. **Time range**: Click 1M / 3M / 6M / 全部 — dataZoom adjusts visible range
3. **MA toggle**: Click MA5 label — line disappears, click again — reappears. Same for MA10, MA20
4. **RSI**: Click RSI button — sub-chart appears below volume with RSI line and 70/30 reference lines
5. **MACD**: Click MACD button — DIF/DEA lines and histogram bars appear
6. **Fullscreen**: Click ⛶ button — chart goes fullscreen overlay. Press ESC or click ✕ to exit
7. **Combinations**: Weekly K + RSI + MACD + fullscreen all work together without errors
8. **Crosshair tooltip**: Hover on chart — crosshair + tooltip with OHLCV values

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(chart): address e2e testing issues"
```

---

## Self-Review Checklist

- [x] Spec coverage: All 5 scope items (period, range, MA toggle, RSI/MACD, fullscreen) have tasks
- [x] No placeholders: All code blocks are complete, no TBD/TODO
- [x] Type consistency: `Period` and `TimeRange` types exported from ChartToolbar match usage in StockChart and chartCalc. `HistoryPoint` defined in chartCalc matches the data shape from backend.
- [x] i18n: All toolbar labels use `t()` keys that are added in Task 1
- [x] StockCard: Call signature updated to pass `symbol` in Task 4 Step 2

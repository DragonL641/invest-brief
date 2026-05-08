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
  const [showVOL, setShowVOL] = useState(false);
  const [showRSI, setShowRSI] = useState(false);
  const [showMACD, setShowMACD] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const aggregated = useMemo(
    () => aggregatePeriod(history, period),
    [history, period]
  );

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
      h.close >= h.open ? "rgba(239,68,68,0.7)" : "rgba(34,197,94,0.7)"
    );

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

    const rsiData = showRSI ? calcRSI(closes) : [];
    const macdData = showMACD ? calcMACD(closes) : null;
    const subCount = [showVOL, showRSI, showMACD].filter(Boolean).length;

    // Dynamic grid layout with adequate spacing
    const GAP = 8; // % gap between grids
    const BOTTOM_PAD = 10; // reserved for dataZoom slider
    const VOL_H = 14;
    const SUB_H = 14;
    const kHeight = 100 - BOTTOM_PAD - (showVOL ? VOL_H : 0) * 1 - (showRSI ? SUB_H : 0) * 1 - (showMACD ? SUB_H : 0) * 1 - (1 + subCount) * GAP - 3;

    const gridBase = { left: 48, right: 16 };
    let cursor = 3; // top padding for title

    // Grid 0: K-line
    const kTop = cursor;
    cursor += kHeight + GAP;

    // Grid 1: Volume (conditional)
    let volTop = 0;

    const grids: any[] = [
      { ...gridBase, top: `${kTop}%`, height: `${kHeight}%` },
    ];

    const subLabelStyle = { color: "rgba(255,255,255,0.5)", fontSize: 10, ...mono };

    // Titles for each grid
    const titles: any[] = [
      {
        text: symbol || "",
        left: 52,
        top: 0,
        textStyle: { color: "#fff", fontSize: 12, fontWeight: 600, ...mono },
      },
    ];

    if (showVOL) {
      volTop = cursor;
      cursor += VOL_H + GAP;
      grids.push({ ...gridBase, top: `${volTop}%`, height: `${VOL_H}%` });
      titles.push({
        text: "VOL",
        left: 52,
        top: `${volTop}%`,
        textStyle: subLabelStyle,
      });
    }

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
    ];
    const dataZoomXAxisIdxs = [0];

    if (showVOL) {
      const idx = grids.length;
      xAxes.push({
        type: "category",
        gridIndex: idx,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.12)" } },
        axisLabel: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
      });
      yAxes.push({
        scale: true,
        gridIndex: idx,
        splitNumber: 1,
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
      });
      series.push({
        name: "Volume",
        type: "bar",
        xAxisIndex: idx,
        yAxisIndex: idx,
        data: volumes,
        itemStyle: {
          color: (params: any) => volumeColors[params.dataIndex],
        },
      });
      dataZoomXAxisIdxs.push(idx);
    }

    if (showRSI) {
      const idx = grids.length;
      const rsiTop = cursor;
      cursor += SUB_H + GAP;
      grids.push({ ...gridBase, top: `${rsiTop}%`, height: `${SUB_H}%` });
      titles.push({
        text: "RSI(14)",
        left: 52,
        top: `${rsiTop}%`,
        textStyle: subLabelStyle,
      });
      xAxes.push({
        type: "category",
        gridIndex: idx,
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
        splitNumber: 1,
        gridIndex: idx,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)", type: "dashed" } },
        axisLabel: { color: "#8d969e", fontSize: 9, ...mono },
      });
      series.push({
        name: "RSI",
        type: "line",
        xAxisIndex: idx,
        yAxisIndex: idx,
        data: rsiData,
        showSymbol: false,
        lineStyle: { width: 1, color: "#f59e0b" },
        itemStyle: { color: "#f59e0b" },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { type: "dashed", width: 1 },
          data: [
            { yAxis: 70, lineStyle: { color: "rgba(239,68,68,0.4)" }, label: { show: false } },
            { yAxis: 30, lineStyle: { color: "rgba(34,197,94,0.4)" }, label: { show: false } },
          ],
        },
      });
      dataZoomXAxisIdxs.push(idx);
    }

    if (showMACD && macdData) {
      const idx = grids.length;
      const macdTop = cursor;
      cursor += SUB_H + GAP;
      grids.push({ ...gridBase, top: `${macdTop}%`, height: `${SUB_H}%` });
      titles.push({
        text: "MACD(12,26,9)",
        left: 52,
        top: `${macdTop}%`,
        textStyle: subLabelStyle,
      });
      xAxes.push({
        type: "category",
        gridIndex: idx,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.12)" } },
        axisLabel: { show: false },
        splitLine: { show: false },
        axisTick: { show: false },
      });
      yAxes.push({
        scale: true,
        splitNumber: 1,
        gridIndex: idx,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: "#8d969e", fontSize: 9, ...mono },
      });
      const macdHistColors = (macdData.histogram as (number | null)[]).map(
        (v) => (v != null && v >= 0 ? "rgba(239,68,68,0.7)" : "rgba(34,197,94,0.7)")
      );
      series.push(
        {
          name: "DIF",
          type: "line",
          xAxisIndex: idx,
          yAxisIndex: idx,
          data: macdData.dif,
          showSymbol: false,
          lineStyle: { width: 1, color: "#f59e0b" },
          itemStyle: { color: "#f59e0b" },
        },
        {
          name: "DEA",
          type: "line",
          xAxisIndex: idx,
          yAxisIndex: idx,
          data: macdData.dea,
          showSymbol: false,
          lineStyle: { width: 1, color: "#3b82f6" },
          itemStyle: { color: "#3b82f6" },
        },
        {
          name: "MACD",
          type: "bar",
          xAxisIndex: idx,
          yAxisIndex: idx,
          data: macdData.histogram,
          itemStyle: {
            color: (params: any) => macdHistColors[params.dataIndex],
          },
        }
      );
      dataZoomXAxisIdxs.push(idx);
    }

    return {
      animation: false,
      backgroundColor: "transparent",
      title: titles,
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
        link: [{ xAxisIndex: dataZoomXAxisIdxs }],
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
  }, [displayed, visibleMA, showVOL, showRSI, showMACD, isFullscreen]);

  const subChartCount = [showVOL, showRSI, showMACD].filter(Boolean).length;
  const chartHeight = (isFullscreen ? 100 : 320) + subChartCount * 60;

  const toolbar = (
    <ChartToolbar
      period={period}
      onPeriodChange={setPeriod}
      range={range}
      onRangeChange={setRange}
      visibleMA={visibleMA}
      onToggleMA={toggleMA}
      showVOL={showVOL}
      onToggleVOL={() => setShowVOL((v) => !v)}
      showRSI={showRSI}
      onToggleRSI={() => setShowRSI((v) => !v)}
      showMACD={showMACD}
      onToggleMACD={() => setShowMACD((v) => !v)}
      isFullscreen={isFullscreen}
      onToggleFullscreen={() => setIsFullscreen((v) => !v)}
    />
  );

  const chartKey = `${showVOL ? 1 : 0}${showRSI ? 1 : 0}${showMACD ? 1 : 0}`;

  const chart = (
    <ReactECharts
      key={chartKey}
      option={option}
      style={{ height: chartHeight, width: "100%" }}
      notMerge={true}
      lazyUpdate={true}
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

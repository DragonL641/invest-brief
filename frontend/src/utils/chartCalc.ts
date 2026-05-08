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

  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1];
    if (delta > 0) avgGain += delta;
    else avgLoss += Math.abs(delta);
  }
  avgGain /= period;
  avgLoss /= period;

  for (let i = 0; i < period; i++) result.push(null);

  const rs0 = avgLoss === 0 ? 100 : avgGain / avgLoss;
  result.push(+(100 - 100 / (1 + rs0)).toFixed(2));

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

  const difValues = dif.filter((v) => v != null) as number[];
  const deaFull = calcEMA(difValues, 9);

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

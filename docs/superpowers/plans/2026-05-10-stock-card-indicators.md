# StockCard Indicator Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance StockCard with analyst detail modal, technical indicator tooltips, and stacked bottom layout.

**Architecture:** Three independent UI changes in the frontend only — no backend changes needed. Add InfoTooltip as a small reusable component, AnalystDetailModal as a separate component, and refactor StockCard's bottom layout from two-column to stacked.

**Tech Stack:** React 18, TypeScript, react-i18next, inline CSS (matching existing pattern)

---

### Task 1: Add i18n translation keys

**Files:**
- Modify: `frontend/src/i18n/zh-CN.json`
- Modify: `frontend/src/i18n/ko-KR.json`

- [ ] **Step 1: Add keys to zh-CN.json**

Append the following keys inside the JSON object (before the closing `}`), adding a comma after the last existing key `"calendar.previous"`:

```json
  "stock.analystCount": "{{count}} 位分析师",
  "stock.viewDetails": "查看详情",
  "stock.analystModal.title": "分析师详情",
  "stock.analystModal.rating": "评级分布",
  "stock.analystModal.upgrades": "评级变动",
  "stock.analystModal.firm": "机构",
  "stock.analystModal.grade": "评级",
  "stock.analystModal.targetPrice": "目标价",
  "stock.analystModal.date": "日期",
  "stock.analystModal.noData": "暂无数据",
  "stock.analystModal.close": "关闭",
  "tooltip.rsi": "范围 0-100。>70 超买（可能回调），<30 超卖（可能反弹）。衡量近期涨跌力度。",
  "tooltip.sma50": "50 日简单移动均线。价格在其上方为中期上升趋势，下方为下降趋势。",
  "tooltip.sma200": "200 日简单移动均线。长期趋势分水岭，价格在其上方通常视为牛市。",
  "tooltip.macd": "MACD 柱状图为正表示短期动量向上（金叉），为负表示向下（死叉）。",
  "tooltip.currentEps": "分析师对当前季度每股收益的平均预期。",
  "tooltip.nextEps": "分析师对下个季度每股收益的平均预期。",
  "tooltip.surprise": "上季实际 EPS 与预期的偏差百分比。正值超预期，负值不及预期。"
```

- [ ] **Step 2: Add keys to ko-KR.json**

Append the same keys with Korean translations (after the last existing key `"calendar.previous"`):

```json
  "stock.analystCount": "애널리스트 {{count}}명",
  "stock.viewDetails": "상세 보기",
  "stock.analystModal.title": "애널리스트 상세",
  "stock.analystModal.rating": "평가 분포",
  "stock.analystModal.upgrades": "평가 변경",
  "stock.analystModal.firm": "기관",
  "stock.analystModal.grade": "평가",
  "stock.analystModal.targetPrice": "목표가",
  "stock.analystModal.date": "날짜",
  "stock.analystModal.noData": "데이터 없음",
  "stock.analystModal.close": "닫기",
  "tooltip.rsi": "범위 0-100. >70 과매수(조정 가능성), <30 과매도(반등 가능성). 최근 가격 상승/하락 강도 측정.",
  "tooltip.sma50": "50일 단순이동평균선. 가격이上方이면 중기 상승추세, 下方이면 하락추세.",
  "tooltip.sma200": "200일 단순이동평균선. 장기 추세 분기점, 가격이上方이면 보통 강세장으로 간주.",
  "tooltip.macd": "MACD 히스토그램이 양수면 단기 모멘텀 상승(골든크로스), 음수면 하락(데드크로스).",
  "tooltip.currentEps": "이번 분기 주당순이익에 대한 애널리스트 평균 예상.",
  "tooltip.nextEps": "다음 분기 주당순이익에 대한 애널리스트 평균 예상.",
  "tooltip.surprise": "이전 분기 실제 EPS와 예상의 차이 %. 양수면 예상 초과, 음수면 예상 미달."
```

- [ ] **Step 3: Verify JSON is valid**

Run: `node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/zh-CN.json','utf8')); JSON.parse(require('fs').readFileSync('frontend/src/i18n/ko-KR.json','utf8')); console.log('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/zh-CN.json frontend/src/i18n/ko-KR.json
git commit -m "feat(i18n): add tooltip and analyst modal translation keys"
```

---

### Task 2: Create InfoTooltip component

**Files:**
- Create: `frontend/src/components/InfoTooltip.tsx`

This is a small reusable component: a circled "i" icon that shows a tooltip on hover.

- [ ] **Step 1: Create InfoTooltip.tsx**

```tsx
import { useState } from "react";

interface InfoTooltipProps {
  text: string;
}

export default function InfoTooltip({ text }: InfoTooltipProps) {
  const [show, setShow] = useState(false);

  return (
    <span
      style={{ position: "relative", display: "inline-flex", alignItems: "center", marginLeft: 4, cursor: "help" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          border: "1px solid rgba(255,255,255,0.3)",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 10,
          color: "rgba(255,255,255,0.5)",
          flexShrink: 0,
        }}
      >
        i
      </span>
      {show && (
        <span
          style={{
            position: "absolute",
            bottom: "100%",
            left: "50%",
            transform: "translateX(-50%)",
            marginBottom: 6,
            background: "#2a2d30",
            color: "#e0e0e0",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 11,
            lineHeight: 1.4,
            width: 200,
            whiteSpace: "normal",
            zIndex: 50,
            boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
            pointerEvents: "none",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit src/components/InfoTooltip.tsx 2>&1 | tail -5`

Expected: no errors (empty output or just file name)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/InfoTooltip.tsx
git commit -m "feat(ui): add InfoTooltip component for indicator help"
```

---

### Task 3: Create AnalystDetailModal component

**Files:**
- Create: `frontend/src/components/AnalystDetailModal.tsx`

This modal shows full rating distribution (with absolute counts) and an upgrades/downgrades table.

- [ ] **Step 1: Create AnalystDetailModal.tsx**

```tsx
import { useTranslation } from "react-i18next";

const mono: React.CSSProperties = { fontFamily: "'Geist Mono', monospace" };

interface Upgrade {
  firm?: string;
  institution?: string;
  to_grade?: string;
  from_grade?: string;
  action?: string;
  grade?: string;
  change?: string;
  price_target?: number | null;
  date?: string;
}

interface Recommendations {
  strong_buy: number;
  buy: number;
  hold: number;
  sell: number;
  strong_sell: number;
}

interface AnalystDetailModalProps {
  targets: { low?: number; mean?: number; high?: number; median?: number };
  upsidePct: number | null | undefined;
  recommendations: Recommendations | null;
  upgrades: Upgrade[];
  onClose: () => void;
}

function fmt(n: number | undefined | null, decimals = 2): string {
  if (n == null) return "--";
  return n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export default function AnalystDetailModal({
  targets, upsidePct, recommendations, upgrades, onClose,
}: AnalystDetailModalProps) {
  const { t } = useTranslation();

  const rec = recommendations;
  const totalBuy = (rec?.strong_buy ?? 0) + (rec?.buy ?? 0);
  const totalHold = rec?.hold ?? 0;
  const totalSell = (rec?.strong_sell ?? 0) + (rec?.sell ?? 0);
  const total = totalBuy + totalHold + totalSell;
  const buyPct = total ? Math.round((totalBuy / total) * 100) : 0;
  const holdPct = total ? Math.round((totalHold / total) * 100) : 0;
  const sellPct = total ? 100 - buyPct - holdPct : 0;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 100, padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#1a1c1e", borderRadius: 16, padding: 24,
          maxWidth: 520, width: "100%", maxHeight: "80vh", overflow: "auto",
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>{t("stock.analystModal.title")}</span>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: "#8d969e", cursor: "pointer", fontSize: 18, padding: 4 }}
          >
            ✕
          </button>
        </div>

        {/* Target price */}
        {targets.mean != null && (
          <div style={{ display: "flex", gap: 24, marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.target")}</div>
              <div style={{ ...mono, fontSize: 20, fontWeight: 600, color: "#fff" }}>${fmt(targets.mean)}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.upside")}</div>
              <div style={{
                ...mono, fontSize: 20, fontWeight: 600,
                color: (upsidePct ?? 0) >= 0 ? "#22c55e" : "#ef4444",
              }}>
                {upsidePct != null ? `${upsidePct >= 0 ? "+" : ""}${upsidePct.toFixed(2)}%` : "--"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.52wRange")}</div>
              <div style={{ ...mono, fontSize: 14, color: "#fff" }}>
                ${fmt(targets.low)} - ${fmt(targets.high)}
              </div>
            </div>
          </div>
        )}

        {/* Rating distribution */}
        {total > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
              {t("stock.analystModal.rating")}
            </div>
            <div style={{ display: "flex", gap: 2, height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 8 }}>
              <div style={{ flex: buyPct, background: "#ef4444", borderRadius: 5 }} />
              <div style={{ flex: holdPct, background: "#494fdf", borderRadius: 5 }} />
              <div style={{ flex: sellPct, background: "#22c55e", borderRadius: 5 }} />
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.buy")} {totalBuy}({buyPct}%)</span>
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.hold")} {totalHold}({holdPct}%)</span>
              <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.sell")} {totalSell}({sellPct}%)</span>
            </div>
          </div>
        )}

        {/* Upgrades table */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.analystModal.upgrades")}
          </div>
          {upgrades.length > 0 ? (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.12)" }}>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.firm")}</th>
                  <th style={{ textAlign: "left", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.grade")}</th>
                  <th style={{ textAlign: "right", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.targetPrice")}</th>
                  <th style={{ textAlign: "right", padding: "6px 8px", color: "#8d969e", fontWeight: 500 }}>{t("stock.analystModal.date")}</th>
                </tr>
              </thead>
              <tbody>
                {upgrades.slice(0, 10).map((u, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                    <td style={{ padding: "6px 8px", color: "#fff", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {u.firm || u.institution}
                    </td>
                    <td style={{ padding: "6px 8px", color: "#e0e0e0" }}>
                      {u.from_grade && u.to_grade ? `${u.from_grade} → ${u.to_grade}` : u.change || u.grade || ""}
                    </td>
                    <td style={{ ...mono, padding: "6px 8px", textAlign: "right", color: "#fff" }}>
                      {u.price_target != null ? `$${fmt(u.price_target, 0)}` : "--"}
                    </td>
                    <td style={{ padding: "6px 8px", textAlign: "right", color: "#8d969e" }}>
                      {u.date || "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <span style={{ fontSize: 12, color: "#8d969e" }}>{t("stock.analystModal.noData")}</span>
          )}
        </div>

        {/* Close button */}
        <div style={{ marginTop: 20, textAlign: "right" }}>
          <button
            onClick={onClose}
            style={{
              background: "rgba(255,255,255,0.1)", border: "none", color: "#fff",
              padding: "8px 20px", borderRadius: 8, cursor: "pointer", fontSize: 13,
            }}
          >
            {t("stock.analystModal.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit src/components/AnalystDetailModal.tsx 2>&1 | tail -5`

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AnalystDetailModal.tsx
git commit -m "feat(ui): add AnalystDetailModal component"
```

---

### Task 4: Refactor StockCard — analyst target section with count and detail button

**Files:**
- Modify: `frontend/src/components/StockCard.tsx`

This task changes the analyst target section to show absolute counts, analyst total, and a "view details" button that opens the modal. It also adds modal state and removes the old upgrades section.

- [ ] **Step 1: Add imports at the top of StockCard.tsx**

Add after the existing imports (line 3):

```tsx
import InfoTooltip from "./InfoTooltip";
import AnalystDetailModal from "./AnalystDetailModal";
```

- [ ] **Step 2: Add modal state inside the component function**

After the line `const { t } = useTranslation();` (line 68), add:

```tsx
const [showAnalystModal, setShowAnalystModal] = useState(false);
```

And add `useState` to the existing React import on line 1:

```tsx
import { useState, useEffect, useRef } from "react";
```

Wait — `useEffect` and `useRef` are not currently imported. The current import is just:

```tsx
import { useEffect, useRef } from "react";
```

Change it to:

```tsx
import { useEffect, useRef, useState } from "react";
```

- [ ] **Step 3: Replace the analyst target section**

Replace the entire `{/* Analyst target */}` block (approximately lines 156-188) with:

```tsx
      {/* Analyst target */}
      {targetMean != null && (
        <div style={{ borderTop: "1px solid rgba(255,255,255,0.12)", paddingTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)" }}>
              {t("stock.analystTarget")}
            </span>
            {totalRating > 0 && (
              <span style={{ fontSize: 11, color: "#8d969e" }}>
                {t("stock.analystCount", { count: totalRating })}
              </span>
            )}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.target")}</div>
              <div style={{ ...mono, fontSize: 18, fontWeight: 600, color: "#fff" }}>${fmt(targetMean)}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.upside")}</div>
              <div style={{ ...mono, fontSize: 18, fontWeight: 600, color: (upsidePct ?? 0) >= 0 ? "#22c55e" : "#ef4444" }}>
                {pct(upsidePct)}
              </div>
            </div>
          </div>
          {totalRating > 0 && (
            <>
              <div style={{ display: "flex", gap: 2, height: 8, borderRadius: 4, overflow: "hidden" }}>
                <div style={{ flex: buyPct, background: "#ef4444", borderRadius: 4 }} />
                <div style={{ flex: holdPct, background: "#494fdf", borderRadius: 4 }} />
                <div style={{ flex: sellPct, background: "#22c55e", borderRadius: 4 }} />
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 6 }}>
                <span style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.buy")} {totalBuy}({buyPct}%)</span>
                <span style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.hold")} {totalHold}({holdPct}%)</span>
                <span style={{ fontSize: 11, color: "#8d969e" }}>{t("stock.sell")} {totalSell}({sellPct}%)</span>
              </div>
            </>
          )}
          <button
            onClick={() => setShowAnalystModal(true)}
            style={{
              marginTop: 8, width: "100%", padding: "6px 0",
              background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, color: "#8d969e", fontSize: 12, cursor: "pointer",
            }}
          >
            {t("stock.viewDetails")} →
          </button>
        </div>
      )}

      {/* Analyst detail modal */}
      {showAnalystModal && (
        <AnalystDetailModal
          targets={targets}
          upsidePct={upsidePct}
          recommendations={rec ?? null}
          upgrades={upgrades}
          onClose={() => setShowAnalystModal(false)}
        />
      )}
```

- [ ] **Step 4: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit src/components/StockCard.tsx 2>&1 | tail -5`

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StockCard.tsx
git commit -m "feat(stock-card): add analyst detail modal with counts"
```

---

### Task 5: Refactor StockCard — bottom layout to stacked sections with tooltips

**Files:**
- Modify: `frontend/src/components/StockCard.tsx`

This task replaces the two-column bottom layout with stacked full-width sections, adds InfoTooltip to technical and EPS indicators, and removes the old upgrades section.

- [ ] **Step 1: Replace the two-column bottom section**

Replace the entire `{/* Two-column bottom */}` block (approximately lines 191-265) with:

```tsx
      {/* Stacked bottom sections */}
      <div style={{ borderTop: "1px solid rgba(255,255,255,0.12)", paddingTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Technicals — 2x2 grid */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.technicals")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 24px" }}>
            {[
              { label: "RSI", value: (tech.rsi ?? tech.rsi_14) != null ? fmt(tech.rsi ?? tech.rsi_14, 1) : "--", tooltip: t("tooltip.rsi") },
              { label: "SMA 50", value: (tech.sma50 ?? tech.sma_50) != null ? `$${fmt(tech.sma50 ?? tech.sma_50)}` : "--", tooltip: t("tooltip.sma50") },
              { label: "SMA 200", value: (tech.sma200 ?? tech.sma_200) != null ? `$${fmt(tech.sma200 ?? tech.sma_200)}` : "--", tooltip: t("tooltip.sma200") },
              { label: "MACD", value: (tech.macd ?? tech.macd_line) != null ? fmt(tech.macd ?? tech.macd_line, 4) : "--", tooltip: t("tooltip.macd") },
            ].map((row) => (
              <div key={row.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "#8d969e", display: "flex", alignItems: "center" }}>
                  {row.label}
                  <InfoTooltip text={row.tooltip} />
                </span>
                <span style={{ ...mono, fontSize: 12, color: "#fff" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* EPS — horizontal row */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.eps")}
          </div>
          <div style={{ display: "flex", gap: 24 }}>
            {[
              { label: t("stock.currentQ"), value: (eps.current_q ?? eps["0q"]?.avg) != null ? `$${fmt(eps.current_q ?? eps["0q"]?.avg)}` : "--", tooltip: t("tooltip.currentEps") },
              { label: t("stock.nextQ"), value: (eps.next_q ?? eps["+1q"]?.avg) != null ? `$${fmt(eps.next_q ?? eps["+1q"]?.avg)}` : "--", tooltip: t("tooltip.nextEps") },
              { label: t("stock.surprise"), value: (eps.surprise_pct ?? (earningsHistory.length > 0 ? earningsHistory[earningsHistory.length - 1]?.surprise_pct : null)) != null ? pct(eps.surprise_pct ?? (earningsHistory.length > 0 ? earningsHistory[earningsHistory.length - 1]?.surprise_pct : null)) : "--", tooltip: t("tooltip.surprise") },
            ].map((row) => (
              <div key={row.label} style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 11, color: "#8d969e", display: "flex", alignItems: "center" }}>
                  {row.label}
                  <InfoTooltip text={row.tooltip} />
                </span>
                <span style={{ ...mono, fontSize: 13, color: "#fff" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Insider — full width, up to 5 rows */}
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "rgba(255,255,255,0.72)", marginBottom: 8 }}>
            {t("stock.insider")}
          </div>
          {insiderTrades.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {insiderTrades.slice(0, 5).map((it: any, i: number) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 12, color: "#8d969e", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}>
                    {it.name || it.insider}{it.position ? ` (${it.position})` : ""}
                  </span>
                  <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    {it.value != null && <span style={{ ...mono, fontSize: 11, color: "#8d969e" }}>${fmt(it.value, 0)}</span>}
                    {it.date && <span style={{ ...mono, fontSize: 11, color: "#8d969e" }}>{it.date}</span>}
                    <span style={{ ...mono, fontSize: 12, color: (it.action || it.type || it.transaction || "").toLowerCase().includes("buy") ? "#ef4444" : "#22c55e" }}>
                      {it.action || it.type || it.transaction}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <span style={{ fontSize: 12, color: "#8d969e" }}>--</span>
          )}
        </div>
      </div>
```

Note: The old `{/* Upgrades */}` block is completely removed — it was inside the old two-column layout and is now replaced by the Modal from Task 4.

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit src/components/StockCard.tsx 2>&1 | tail -5`

Expected: no errors

- [ ] **Step 3: Visual verification**

Run: `cd frontend && npm run dev` and open the dashboard in a browser. Check:
- Analyst target section shows analyst count, absolute numbers, and "view details" button
- Modal opens with rating distribution and upgrades table
- Bottom section is stacked: Technicals (2x2 grid with info icons), EPS (horizontal row with info icons), Insider (5 rows)
- Old upgrades section is gone
- Tooltips appear on hover over info icons

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/StockCard.tsx
git commit -m "feat(stock-card): stacked layout with tooltips, remove old upgrades section"
```

---

## Self-Review

**Spec coverage:**
- Analyst count + absolute numbers — Task 4 Step 3
- "View details" button → Modal — Task 4 Step 3
- Modal: rating distribution + upgrades table — Task 3 Step 1
- Technicals tooltips (RSI, SMA50, SMA200, MACD) — Task 5 Step 1
- EPS tooltips (currentQ, nextQ, surprise) — Task 5 Step 1
- Stacked layout (Technicals 2x2, EPS horizontal, Insider full-width) — Task 5 Step 1
- Insider 5 rows — Task 5 Step 1
- Remove old upgrades section — Task 5 Step 1 (replaced by stacked layout)
- i18n keys for all new text — Task 1

**Type consistency:**
- `Upgrade` interface in AnalystDetailModal matches the shape returned by `yfinance.get_upgrades_downgrades` (firm, to_grade, from_grade, action, price_target, date)
- `Recommendations` interface matches `stock.recommendations` shape (strong_buy, buy, hold, sell, strong_sell)
- `targets` prop uses existing `stock.targets` shape (low, mean, high, median)
- `upgrades` variable in StockCard (line 77) is already `any[]` from `stock.upgrades`, compatible with `Upgrade[]`

**No placeholders found.**

import { useTranslation } from "react-i18next";
import { Table } from "antd";

interface EconomicCalendarProps {
  calendar: any[];
}

const mono: React.CSSProperties = { fontFamily: "'Geist Mono', monospace" };

const EVENT_NAME_MAP: Record<string, string> = {
  // Chinese keys (hardcoded CN calendar + US fallback)
  "FOMC 议息会议": "event.fomc",
  "CPI（消费者价格指数）": "event.cpi",
  "非农就业报告（NFP）": "event.nfp",
  "PCE 物价指数": "event.pce",
  "零售销售": "event.retail",
  "LPR 报价": "event.lpr",
  "官方 PMI": "event.officialPmi",
  "财新 PMI": "event.caixinPmi",
  "CPI/PPI": "event.cpiPpi",
  "社融/M2 数据": "event.creditM2",
  "城镇调查失业率": "event.unemployment",
  // English keys (yfinance)
  "Consumer Price Index": "event.cpi",
  "CPI": "event.cpi",
  "Non Farm Payrolls": "event.nfp",
  "Employment Situation": "event.nfp",
  "Federal Funds Rate": "event.fomc",
  "FOMC Meeting": "event.fomc",
  "GDP": "event.gdp",
  "Gross Domestic Product": "event.gdp",
  "Personal Consumption Expenditures": "event.pce",
  "PCE Price Index": "event.pce",
  "Retail Sales": "event.retail",
  "Unemployment Rate": "event.unemployment",
  "Initial Jobless Claims": "event.joblessClaims",
  "ADP Employment Change": "event.adp",
  "ISM Manufacturing PMI": "event.ismMfg",
  "Consumer Confidence": "event.consumerConfidence",
  "Durable Goods Orders": "event.durableGoods",
};

export default function EconomicCalendar({ calendar }: EconomicCalendarProps) {
  const { t } = useTranslation();

  if (!calendar || calendar.length === 0) return null;

  const columns = [
    {
      title: t("calendar.date"),
      dataIndex: "date",
      key: "date",
      width: 140,
      render: (v: string) => <span style={mono}>{v}</span>,
    },
    {
      title: t("calendar.event"),
      dataIndex: "event",
      key: "event",
      render: (v: string, record: any) => {
        const raw = v ?? record.name;
        return <span style={{ color: "#fff" }}>{t(EVENT_NAME_MAP[raw] ?? raw)}</span>;
      },
    },
    {
      title: t("calendar.importance"),
      dataIndex: "importance",
      key: "importance",
      width: 100,
      render: (v: string) => {
        if (!v) return <span style={mono}>--</span>;
        const color = v === "high" ? "#e23b4a" : v === "medium" ? "#ec7e00" : "#8d969e";
        const labelKey = v === "high" ? "calendar.importance.high" : v === "medium" ? "calendar.importance.medium" : "calendar.importance.low";
        return <span style={{ color, fontWeight: 600 }}>{t(labelKey)}</span>;
      },
    },
    {
      title: t("calendar.forecast"),
      dataIndex: "forecast",
      key: "forecast",
      width: 100,
      render: (v: string) => <span style={mono}>{v ?? "--"}</span>,
    },
    {
      title: t("calendar.previous"),
      dataIndex: "previous",
      key: "previous",
      width: 100,
      render: (v: string) => <span style={mono}>{v ?? "--"}</span>,
    },
  ];

  return (
    <section>
      <h2 style={{ color: "#fff", fontSize: 18, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("market.calendar")}
      </h2>
      <div style={{ background: "#111214", borderRadius: 16, overflow: "hidden", boxShadow: "0 1px 3px rgba(0,0,0,0.3)" }}>
        <Table
          dataSource={calendar.map((c, i) => ({ ...c, key: i }))}
          columns={columns}
          pagination={false}
          size="middle"
          style={{ background: "transparent" }}
        />
      </div>
    </section>
  );
}

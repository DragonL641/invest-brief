import { useTranslation } from "react-i18next";
import { Table } from "antd";

interface EconomicCalendarProps {
  calendar: any[];
}

const mono: React.CSSProperties = { fontFamily: "'Geist Mono', monospace" };

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
      render: (v: string, record: any) => <span style={{ color: "#fff" }}>{v ?? record.name}</span>,
    },
    {
      title: t("calendar.importance"),
      dataIndex: "importance",
      key: "importance",
      width: 100,
      render: (v: string) => {
        if (!v) return <span style={mono}>--</span>;
        const color = v === "high" ? "#e23b4a" : v === "medium" ? "#ec7e00" : "#8d969e";
        return <span style={{ color, fontWeight: 600 }}>{v}</span>;
      },
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
      <h2 style={{ color: "#fff", fontSize: 20, fontWeight: 600, margin: "0 0 16px 0" }}>
        {t("market.calendar")}
      </h2>
      <Table
        dataSource={calendar.map((c, i) => ({ ...c, key: i }))}
        columns={columns}
        pagination={false}
        size="middle"
        style={{
          background: "transparent",
        }}
      />
    </section>
  );
}

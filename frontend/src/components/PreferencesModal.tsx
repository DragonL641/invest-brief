import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Tabs, Table, Button, Input, Select, TimePicker, Card, Space, App } from "antd";
import { PlusOutlined, DeleteOutlined, MailOutlined } from "@ant-design/icons";
import type { PreferencesData, DeliveryEntry, HoldingItem, PreferencesUpdate } from "../api/preferences";
import { getPreferences, updatePreferences } from "../api/preferences";

const US_INDUSTRIES = ["semiconductor_ai", "aerospace_defense", "e_commerce", "software_cloud", "ev_automotive"];
const CN_INDUSTRIES = ["semiconductor", "new_energy", "consumer_electronics", "pharmaceuticals", "ai_concept"];

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function PreferencesModal({ open, onClose }: Props) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [holdings, setHoldings] = useState<Record<string, HoldingItem[]>>({});
  const [industries, setIndustries] = useState<Record<string, string[]>>({});
  const [delivery, setDelivery] = useState<DeliveryEntry[]>([]);
  const [newSymbol, setNewSymbol] = useState("");
  const [newName, setNewName] = useState("");
  const [newMarket, setNewMarket] = useState<"us" | "cn">("us");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    getPreferences()
      .then((r) => {
        const mkHoldings: Record<string, HoldingItem[]> = {};
        const mkIndustries: Record<string, string[]> = {};
        for (const [mkt, cfg] of Object.entries(r.data.markets)) {
          mkHoldings[mkt] = (cfg as any).holdings || [];
          mkIndustries[mkt] = (cfg as any).industries || [];
        }
        setHoldings(mkHoldings);
        setIndustries(mkIndustries);
        setDelivery(r.data.delivery || []);
      })
      .catch(() => message.error(t("prefs.saveFailed")))
      .finally(() => setLoading(false));
  }, [open]);

  const handleSave = () => {
    setSaving(true);
    const body: PreferencesUpdate = {
      markets: Object.fromEntries(
        Object.entries(holdings).map(([mkt, h]) => [mkt, { holdings: h, industries: industries[mkt] || [] }])
      ),
      delivery,
    };
    updatePreferences(body)
      .then(() => {
        message.success(t("prefs.saved"));
        onClose();
      })
      .catch(() => message.error(t("prefs.saveFailed")))
      .finally(() => setSaving(false));
  };

  const addHolding = () => {
    if (!newSymbol.trim() || !newName.trim()) return;
    const list = { ...holdings };
    list[newMarket] = [...(list[newMarket] || []), { symbol: newSymbol.trim().toUpperCase(), name: newName.trim() }];
    setHoldings(list);
    setNewSymbol("");
    setNewName("");
  };

  const removeHolding = (market: string, idx: number) => {
    const list = { ...holdings };
    list[market] = (list[market] || []).filter((_, i) => i !== idx);
    setHoldings(list);
  };

  const toggleIndustry = (market: string, ind: string) => {
    const list = { ...industries };
    const current = list[market] || [];
    list[market] = current.includes(ind) ? current.filter((i) => i !== ind) : [...current, ind];
    setIndustries(list);
  };

  const addDeliveryEntry = () => {
    setDelivery([...delivery, { email: "", language: "zh-CN", schedule: {} }]);
  };

  const removeDeliveryEntry = (idx: number) => {
    setDelivery(delivery.filter((_, i) => i !== idx));
  };

  const updateDeliveryEntry = (idx: number, field: string, value: any) => {
    const list = [...delivery];
    list[idx] = { ...list[idx], [field]: value };
    setDelivery(list);
  };

  const addScheduleTime = (entryIdx: number, market: string) => {
    const list = [...delivery];
    const sched = { ...(list[entryIdx].schedule || {}) };
    sched[market] = [...(sched[market] || []), "09:00"];
    list[entryIdx] = { ...list[entryIdx], schedule: sched };
    setDelivery(list);
  };

  const removeScheduleTime = (entryIdx: number, market: string, timeIdx: number) => {
    const list = [...delivery];
    const sched = { ...(list[entryIdx].schedule || {}) };
    sched[market] = (sched[market] || []).filter((_, i) => i !== timeIdx);
    list[entryIdx] = { ...list[entryIdx], schedule: sched };
    setDelivery(list);
  };

  const updateScheduleTime = (entryIdx: number, market: string, timeIdx: number, value: string) => {
    const list = [...delivery];
    const sched = { ...(list[entryIdx].schedule || {}) };
    sched[market] = [...(sched[market] || [])];
    sched[market][timeIdx] = value;
    list[entryIdx] = { ...list[entryIdx], schedule: sched };
    setDelivery(list);
  };

  const holdingsTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {(["us", "cn"] as const).map((mkt) => (
        <div key={mkt}>
          <h4 style={{ color: "#fff", marginBottom: 8 }}>{mkt === "us" ? t("tab.us") : t("tab.cn")}</h4>
          <Table
            dataSource={(holdings[mkt] || []).map((h, i) => ({ ...h, key: `${mkt}-${i}` }))}
            pagination={false}
            size="small"
            columns={[
              { title: t("prefs.holdings.symbol"), dataIndex: "symbol" },
              { title: t("prefs.holdings.name"), dataIndex: "name" },
              {
                title: "",
                width: 60,
                render: (_: any, __: any, idx: number) => (
                  <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={() => removeHolding(mkt, idx)} />
                ),
              },
            ]}
          />
        </div>
      ))}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Select value={newMarket} onChange={setNewMarket} style={{ width: 100 }} options={[{ value: "us", label: "US" }, { value: "cn", label: "CN" }]} />
        <Input placeholder={t("prefs.holdings.symbol")} value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} style={{ width: 120 }} />
        <Input placeholder={t("prefs.holdings.name")} value={newName} onChange={(e) => setNewName(e.target.value)} style={{ width: 140 }} />
        <Button icon={<PlusOutlined />} onClick={addHolding}>{t("prefs.holdings.add")}</Button>
      </div>
      <div style={{ color: "#8d969e", fontSize: 12 }}>{t("prefs.hint")}</div>
    </div>
  );

  const industriesTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {(["us", "cn"] as const).map((mkt) => {
        const list = mkt === "us" ? US_INDUSTRIES : CN_INDUSTRIES;
        const selected = industries[mkt] || [];
        return (
          <div key={mkt}>
            <h4 style={{ color: "#fff", marginBottom: 8 }}>{mkt === "us" ? t("prefs.industries.us") : t("prefs.industries.cn")}</h4>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {list.map((ind) => (
                <Button
                  key={ind}
                  size="small"
                  type={selected.includes(ind) ? "primary" : "default"}
                  onClick={() => toggleIndustry(mkt, ind)}
                >
                  {ind}
                </Button>
              ))}
            </div>
          </div>
        );
      })}
      <div style={{ color: "#8d969e", fontSize: 12 }}>{t("prefs.hint")}</div>
    </div>
  );

  const deliveryTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {delivery.map((entry, idx) => (
        <Card key={idx} size="small" title={<span><MailOutlined /> {entry.email || t("prefs.delivery.addEmail")}</span>}
          extra={<Button type="text" danger size="small" onClick={() => removeDeliveryEntry(idx)}>{t("prefs.delivery.removeEmail")}</Button>}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ color: "#8d969e", width: 50 }}>{t("prefs.delivery.email")}</span>
              <Input value={entry.email} onChange={(e) => updateDeliveryEntry(idx, "email", e.target.value)} style={{ flex: 1 }} />
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ color: "#8d969e", width: 50 }}>{t("prefs.delivery.language")}</span>
              <Select value={entry.language} onChange={(v) => updateDeliveryEntry(idx, "language", v)}
                style={{ width: 120 }} options={[{ value: "zh-CN", label: "中文" }, { value: "ko-KR", label: "한국어" }]} />
            </div>
            <div>
              <span style={{ color: "#8d969e" }}>{t("prefs.delivery.schedule")}</span>
              {(["us", "cn"] as const).map((mkt) => (
                <div key={mkt} style={{ marginTop: 8 }}>
                  <span style={{ color: "#aaa", fontSize: 12 }}>{mkt.toUpperCase()}</span>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4, alignItems: "center" }}>
                    {(entry.schedule?.[mkt] || []).map((time, ti) => (
                      <span key={ti} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                        <TimePicker
                          format="HH:mm"
                          value={(() => { const [h, m] = time.split(":").map(Number); const d = new Date(); d.setHours(h, m, 0, 0); return d; })()}
                          onChange={(_, timeStr) => { if (timeStr) updateScheduleTime(idx, mkt, ti, timeStr); }}
                          size="small"
                        />
                        <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={() => removeScheduleTime(idx, mkt, ti)} />
                      </span>
                    ))}
                    <Button size="small" onClick={() => addScheduleTime(idx, mkt)}>{t("prefs.delivery.addTime")}</Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      ))}
      <Button icon={<PlusOutlined />} onClick={addDeliveryEntry}>{t("prefs.delivery.addEmail")}</Button>
    </div>
  );

  return (
    <Modal
      title={t("prefs.title")}
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      okText={t("prefs.save")}
      cancelText={t("prefs.cancel")}
      confirmLoading={saving}
      width={680}
    >
      <Tabs items={[
        { key: "holdings", label: t("prefs.holdings"), children: holdingsTab },
        { key: "industries", label: t("prefs.industries"), children: industriesTab },
        { key: "delivery", label: t("prefs.delivery"), children: deliveryTab },
      ]} />
    </Modal>
  );
}

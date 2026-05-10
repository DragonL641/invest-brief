import { Alert } from "antd";
import { useTranslation } from "react-i18next";

export interface FetchError {
  section: string;
  reason: string;
  detail?: string;
}

interface Props {
  errors: FetchError[];
  onClose: () => void;
}

const sectionKeyMap: Record<string, string> = {
  indices: "error.sectionIndices",
  holdings: "error.sectionHoldings",
  news: "error.sectionNews",
  recommendations: "error.sectionRecommendations",
  economic_calendar: "error.sectionEconomic_calendar",
  calendar: "error.sectionCalendar",
  premarket_movers: "error.sectionPremarket_movers",
  earnings_calendar: "error.sectionEarnings_calendar",
  congressional_trades: "error.sectionCongressional_trades",
  dragon_tiger: "error.sectionDragon_tiger",
  sector_performance: "error.sectionSector_performance",
};

const solutionKeyMap: Record<string, string> = {
  timeout: "error.solutionTimeout",
  network: "error.solutionNetwork",
  api_error: "error.solutionApi_error",
  auth: "error.solutionAuth",
  rate_limited: "error.solutionRate_limited",
  unknown: "error.solutionUnknown",
};

export default function DataErrorBanner({ errors, onClose }: Props) {
  const { t } = useTranslation();
  if (errors.length === 0) return null;

  const now = new Date();
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const titleKey = errors.length >= 5 ? "error.bannerTitleFull" : "error.bannerTitle";

  const items = errors.map((e) => {
    const sectionName = t(sectionKeyMap[e.section] ?? e.section);
    const solutionText = t(solutionKeyMap[e.reason] ?? solutionKeyMap.unknown);
    return `${sectionName}：${solutionText}`;
  });

  return (
    <Alert
      type="error"
      closable
      onClose={onClose}
      showIcon
      message={t(titleKey, { time })}
      description={
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {items.map((text, i) => (
            <li key={i} style={{ fontSize: 13, lineHeight: "22px" }}>{text}</li>
          ))}
        </ul>
      }
      style={{ marginBottom: 16, borderRadius: 12 }}
    />
  );
}

import { useTranslation } from "react-i18next";

export interface SectionDef {
  id: string;
  titleKey: string;
}

interface SectionNavProps {
  sections: SectionDef[];
  activeId: string;
  onNavigate: (id: string) => void;
}

export default function SectionNav({ sections, activeId, onNavigate }: SectionNavProps) {
  const { t } = useTranslation();

  return (
    <nav
      style={{
        position: "sticky",
        top: 64,
        width: 200,
        minWidth: 200,
        height: "calc(100vh - 64px)",
        padding: "32px 0",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      {sections.map((s) => {
        const isActive = s.id === activeId;
        return (
          <button
            key={s.id}
            onClick={() => onNavigate(s.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 20px",
              fontSize: 14,
              fontWeight: 500,
              color: isActive ? "#fff" : "#8d969e",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              textAlign: "left",
              position: "relative",
              transition: "color 0.2s",
            }}
          >
            {isActive && (
              <span
                style={{
                  position: "absolute",
                  left: 0,
                  top: "50%",
                  transform: "translateY(-50%)",
                  width: 2,
                  height: 16,
                  borderRadius: 1,
                  background: "#494fdf",
                }}
              />
            )}
            {t(s.titleKey)}
          </button>
        );
      })}
    </nav>
  );
}

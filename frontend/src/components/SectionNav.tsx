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
        zIndex: 100,
        background: "#000",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        padding: "0 40px",
      }}
    >
      <div
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          display: "flex",
          gap: 0,
          overflowX: "auto",
          scrollbarWidth: "none",
        }}
      >
        {sections.map((s) => {
          const isActive = s.id === activeId;
          return (
            <button
              key={s.id}
              onClick={() => onNavigate(s.id)}
              style={{
                padding: "12px 20px",
                fontSize: 14,
                fontWeight: isActive ? 600 : 500,
                color: isActive ? "#fff" : "#8d969e",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                position: "relative",
                whiteSpace: "nowrap",
                transition: "color 0.2s",
              }}
            >
              {t(s.titleKey)}
              {isActive && (
                <span
                  style={{
                    position: "absolute",
                    bottom: 0,
                    left: 20,
                    right: 20,
                    height: 2,
                    background: "#494fdf",
                    borderRadius: 1,
                  }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

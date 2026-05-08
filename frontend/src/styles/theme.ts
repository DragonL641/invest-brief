import type { ThemeConfig } from "antd";

const theme: ThemeConfig = {
  token: {
    colorPrimary: "#494fdf",
    colorBgContainer: "#16181a",
    colorBgLayout: "#000000",
    colorBgElevated: "#16181a",
    colorText: "#ffffff",
    colorTextSecondary: "rgba(255,255,255,0.72)",
    colorTextTertiary: "#8d969e",
    colorBorder: "rgba(255,255,255,0.12)",
    borderRadius: 12,
    fontFamily: "Inter, system-ui, sans-serif",
  },
  components: {
    Button: { borderRadius: 9999, controlHeight: 40 },
    Card: { colorBgContainer: "#16181a", borderRadiusLG: 20 },
    Input: { borderRadius: 12, colorBgContainer: "#0a0a0a", controlHeight: 48 },
    Table: { colorBgContainer: "#16181a" },
    Tabs: { inkBarColor: "#494fdf", itemActiveColor: "#494fdf", itemSelectedColor: "#494fdf" },
  },
};
export default theme;

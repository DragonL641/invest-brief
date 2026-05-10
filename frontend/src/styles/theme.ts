import type { ThemeConfig } from "antd";

const theme: ThemeConfig = {
  token: {
    colorPrimary: "#494fdf",
    colorBgContainer: "#111214",
    colorBgLayout: "#000000",
    colorBgElevated: "#111214",
    colorText: "#ffffff",
    colorTextSecondary: "rgba(255,255,255,0.72)",
    colorTextTertiary: "#8d969e",
    colorBorder: "rgba(255,255,255,0.08)",
    borderRadius: 8,
    fontFamily: "'DM Sans', system-ui, sans-serif",
  },
  components: {
    Button: { borderRadius: 9999, controlHeight: 40 },
    Card: { colorBgContainer: "#111214", borderRadiusLG: 16 },
    Input: { borderRadius: 8, colorBgContainer: "#0a0a0b", controlHeight: 48 },
    Table: { colorBgContainer: "#111214" },
    Tabs: { inkBarColor: "#494fdf", itemActiveColor: "#494fdf", itemSelectedColor: "#494fdf" },
  },
};
export default theme;

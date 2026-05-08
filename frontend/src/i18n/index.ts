import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhCN from "./zh-CN.json";
import koKR from "./ko-KR.json";

i18n.use(initReactI18next).init({
  resources: { "zh-CN": { translation: zhCN }, "ko-KR": { translation: koKR } },
  lng: "zh-CN",
  fallbackLng: "zh-CN",
  interpolation: { escapeValue: false },
});
export default i18n;

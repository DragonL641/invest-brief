import client from "./client";

export interface HoldingItem {
  symbol: string;
  name: string;
}

export interface MarketPreferences {
  holdings: HoldingItem[];
  industries: string[];
}

export interface DeliveryEntry {
  email: string;
  language: string;
  schedule: Record<string, string[]>;
}

export interface PreferencesData {
  markets: Record<string, MarketPreferences>;
  delivery: DeliveryEntry[];
  language: string;
}

export interface PreferencesUpdate {
  markets?: Record<string, MarketPreferences>;
  delivery?: DeliveryEntry[];
}

export const getPreferences = () => client.get<PreferencesData>("/preferences");
export const updatePreferences = (data: PreferencesUpdate) => client.put("/preferences", data);

import client from "./client";
export const getMarketData = (market: string) => client.get(`/data/${market}`);
export const refreshMarket = (market: string) => client.post(`/data/${market}/refresh`);
export const refreshSection = (market: string, section: string) => client.post(`/data/${market}/refresh/${section}`);
export const getStatus = () => client.get("/data/status");

interface StreamSectionPayload {
  section: string;
  data: any;
  status: string;
  error?: any;
  updated_at?: string | null;
}

/**
 * Stream market data via SSE. Calls onSection for each section as it arrives,
 * onDone when the stream completes, or onError on connection failure.
 * Returns an AbortController so the caller can cancel the stream.
 */
export function streamMarketData(
  market: string,
  onSection: (name: string, payload: StreamSectionPayload) => void,
  onDone: () => void,
  onError: (err: unknown) => void,
): AbortController {
  const controller = new AbortController();
  const token = localStorage.getItem("token");

  fetch(`/api/data/${market}/stream`, {
    headers: { Authorization: `Bearer ${token}` },
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(new Error(`HTTP ${res.status}`));
        return;
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop()!;
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") {
            onDone();
            return;
          }
          try {
            const event = JSON.parse(payload);
            if (event.type === "section") {
              onSection(event.section, event);
            } else if (event.type === "done") {
              onDone();
              return;
            }
          } catch {
            // skip malformed lines
          }
        }
      }
      // Stream ended without done event
      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return controller;
}

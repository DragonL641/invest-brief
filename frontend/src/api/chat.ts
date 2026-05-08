export async function* streamChat(message: string, market: string) {
  const token = localStorage.getItem("token");
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message, market }),
  });
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
      if (line.startsWith("data: ") && line !== "data: [DONE]") {
        yield JSON.parse(line.slice(6)).text;
      }
    }
  }
}

export const sectionAnalysis = (section: string, market: string, data: object) => {
  const token = localStorage.getItem("token");
  return fetch("/api/chat/section", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ section, market, data }),
  }).then((r) => r.json());
};

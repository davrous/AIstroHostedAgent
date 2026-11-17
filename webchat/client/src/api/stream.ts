export interface StreamEvent {
  type: string;
  delta?: string;
}

export async function* events(stream: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let complete = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const payload = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).trimStart()).join("\n");
        if (!payload || payload === "[DONE]") continue;
        const value: unknown = JSON.parse(payload);
        if (typeof value !== "object" || value === null || !("type" in value)) {
          if (typeof value === "object" && value !== null && "error" in value) {
            throw new Error("Le flux de l'agent a été interrompu.");
          }
          continue;
        }
        const event = value as Record<string, unknown>;
        if (["response.failed", "response.incomplete", "error"].includes(String(event.type))) {
          throw new Error("L'agent n'a pas terminé sa réponse. Vous pouvez réessayer.");
        }
        if (event.type === "response.completed") complete = true;
        yield {
          type: String(event.type),
          delta: typeof event.delta === "string" ? event.delta : undefined,
        };
      }
      if (done) break;
    }
    if (!complete) throw new Error("La connexion s'est fermée avant la fin de la réponse.");
  } finally {
    reader.releaseLock();
  }
}

export async function requestJson(url: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`Le service est indisponible (HTTP ${response.status}).`);
  return response.json();
}

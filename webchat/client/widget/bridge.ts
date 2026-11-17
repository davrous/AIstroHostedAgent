type JsonObject = Record<string, unknown>;

export function object(value: unknown): JsonObject | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonObject : undefined;
}

export class WidgetBridge {
  onContext?: (context: JsonObject) => void;
  private origin?: string;
  private connection?: Promise<JsonObject>;
  private pending = new Map<string, {
    resolve: (value: JsonObject) => void;
    reject: (error: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  }>();

  constructor() { window.addEventListener("message", this.receive); }

  private receive = (event: MessageEvent) => {
    if (event.source !== window.parent || (this.origin && event.origin !== this.origin)) return;
    let value: unknown = event.data;
    if (typeof value === "string") {
      try { value = JSON.parse(value); } catch { return; }
    }
    const message = object(value);
    if (!message || message.jsonrpc !== "2.0") return;
    if (this.origin && message.method === "ui/notifications/host-context-changed") {
      const context = object(message.params);
      if (context) this.onContext?.(context);
      return;
    }
    if (typeof message.id !== "string") return;
    const request = this.pending.get(message.id);
    if (!request) return;
    this.pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.error) {
      request.reject(new Error("Teams n'a pas pu terminer cet appel. Réessayez."));
      return;
    }
    this.origin ??= event.origin;
    request.resolve(object(message.result) ?? {});
  };

  notify(method: string, params: JsonObject) {
    window.parent.postMessage(
      { jsonrpc: "2.0", method, params },
      this.origin && this.origin !== "null" ? this.origin : "*",
    );
  }

  private request(method: string, params: JsonObject): Promise<JsonObject> {
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("Teams ne répond pas. L'agent peut être en cours de réveil ; réessayez."));
      }, 15000);
      this.pending.set(id, { resolve, reject, timer });
      window.parent.postMessage(
        { jsonrpc: "2.0", id, method, params },
        this.origin && this.origin !== "null" ? this.origin : "*",
      );
    });
  }

  connect(): Promise<JsonObject> {
    this.connection ??= this.request("ui/initialize", {
      protocolVersion: "2026-01-26",
      appInfo: { name: "AIstro", version: "1.0.0" },
      appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
    }).then(result => {
      this.notify("ui/notifications/initialized", {});
      return result;
    }).catch((error: unknown) => { this.connection = undefined; throw error; });
    return this.connection;
  }

  async call(name: "zodiac_widget_ping" | "load_zodiac_snapshot", id: string): Promise<JsonObject> {
    await this.connect();
    const result = await this.request("tools/call", { name, arguments: { id } });
    if (result.isError === true) {
      const content = Array.isArray(result.content) ? result.content.map(object) : [];
      const text = content.find(item => item?.type === "text")?.text;
      throw new Error(typeof text === "string" ? text : "Ce rendu est indisponible.");
    }
    const data = object(result.structuredContent);
    if (!data || data.version !== 1 || data.id !== id) {
      throw new Error("La réponse du widget ne correspond pas au rendu demandé.");
    }
    return data;
  }

  async displayMode(mode: "inline" | "fullscreen"): Promise<void> {
    await this.connect();
    const result = await this.request("ui/request-display-mode", { mode });
    if (result.mode !== mode) throw new Error("Ce client Teams ne peut pas agrandir le widget.");
  }

  dispose() {
    window.removeEventListener("message", this.receive);
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error("Le widget a été fermé."));
    }
    this.pending.clear();
  }
}

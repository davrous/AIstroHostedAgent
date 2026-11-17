import { z } from "zod";
import { ZodiacScene } from "../src/scene/ZodiacScene";
import { formatInstant, sceneSchema } from "../src/scene/schema";
import { object, WidgetBridge } from "./bridge";
import "./style.css";

function element<T extends HTMLElement>(id: string, type: { new(): T }): T {
  const found = document.getElementById(id);
  if (!(found instanceof type)) throw new Error(`Le widget est incomplet : ${id}.`);
  return found;
}

const root = element("root", HTMLElement);
const canvas = element("sky", HTMLCanvasElement);
const load = element("load", HTMLButtonElement);
const reset = element("reset", HTMLButtonElement);
const focus = element("focus", HTMLSelectElement);
const ping = element("ping", HTMLButtonElement);
const fullscreen = element("fullscreen", HTMLButtonElement);
const status = element("status", HTMLElement);
const error = element("error", HTMLElement);
const placeholder = element("placeholder", HTMLElement);
const bridge = new WidgetBridge();
const config = z.object({
  id: z.string().regex(/^[a-f0-9]{32}$/),
  storageOrigin: z.string().url().refine(value =>
    /^https:\/\/[a-z0-9]{3,24}\.blob\.core\.windows\.net$/.test(value)),
}).parse(JSON.parse(document.getElementById("aistro-widget-config")?.textContent ?? ""));

let viewer: ZodiacScene | undefined;
let controller: AbortController | undefined;
let closed = false;
let busy = false;
let full = false;
let fullscreenSupported = false;
let initialized = false;
let height: number | undefined;

function showError(message: string) {
  error.textContent = message;
  error.hidden = false;
  status.textContent = "Le rendu nécessite votre attention.";
}

function hostContext(context: Record<string, unknown>) {
  if (["dark", "light", "high-contrast"].includes(String(context.theme))) {
    root.dataset.theme = String(context.theme);
  }
  if (context.displayMode === "inline" || context.displayMode === "fullscreen") {
    full = context.displayMode === "fullscreen";
    root.dataset.displayMode = context.displayMode;
    fullscreen.textContent = full ? "Réduire" : "Agrandir";
  }
  if (Array.isArray(context.availableDisplayModes)) {
    fullscreenSupported = context.availableDisplayModes.includes("fullscreen");
  }
  fullscreen.disabled = !fullscreenSupported;
}
bridge.onContext = hostContext;
const observer = new ResizeObserver(() => {
  if (full || closed) return;
  const next = root.getBoundingClientRect().height;
  if (height === next) return;
  height = next;
  bridge.notify("ui/notifications/size-changed", { height: next });
});

async function connect() {
  const result = await bridge.connect();
  if (!initialized) {
    const context = object(result.hostContext);
    if (context) hostContext(context);
    initialized = true;
  }
  observer.observe(root);
}

load.addEventListener("click", async () => {
  if (busy || closed) return;
  busy = true;
  load.disabled = ping.disabled = true;
  reset.disabled = focus.disabled = true;
  error.hidden = true;
  placeholder.hidden = false;
  status.textContent = "Autorisation et chargement du rendu…";
  controller?.abort();
  controller = new AbortController();
  const timeout = setTimeout(() => controller?.abort(), 60000);
  viewer?.dispose();
  viewer = undefined;
  try {
    await connect();
    const snapshot = await bridge.call("load_zodiac_snapshot", config.id);
    const size = z.number().int().positive().max(1024 * 1024).parse(snapshot.size);
    const url = new URL(z.string().url().parse(snapshot.url));
    if (url.protocol !== "https:" || url.origin !== config.storageOrigin
      || url.username || url.password || url.hash
      || !new RegExp(`^/[a-z0-9-]+/zodiac/[a-f0-9]{64}/${config.id}/data\\.json$`).test(url.pathname)) {
      throw new Error("L'adresse du rendu astronomique est invalide.");
    }
    const response = await fetch(url.href, {
      signal: controller.signal, credentials: "omit", redirect: "error", cache: "no-store",
    });
    if (!response.ok) throw new Error("Le rendu est indisponible ou son lien a expiré. Rechargez-le.");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== size) throw new Error("La taille du rendu a changé.");
    const data = sceneSchema.parse(JSON.parse(new TextDecoder().decode(bytes)));
    if (closed) return;
    viewer = new ZodiacScene(canvas, data, showError);
    for (const layer of ["stars", "signs", "boundaries"] as const) {
      viewer.setLayer(layer, element(layer, HTMLInputElement).checked);
    }
    element("instant", HTMLElement).textContent = formatInstant(data.instant);
    const sign = data.signs[Math.floor(data.longitude / 30)][0];
    element("solar", HTMLElement).textContent =
      `Soleil : ${sign} · ${(data.longitude % 30).toFixed(4)}° — Constellation UAI : ${data.solarConstellation}`;
    element("license", HTMLElement).textContent = data.catalogueLicense;
    const source = element("source", HTMLAnchorElement);
    source.href = data.requestUrl;
    source.hidden = false;
    focus.replaceChildren(new Option("Vue d'ensemble", ""));
    data.constellations.forEach(item => focus.add(new Option(item.name, item.id)));
    reset.disabled = focus.disabled = false;
    placeholder.hidden = true;
    load.textContent = "Recharger";
    status.textContent = "Vue prête. Glissez pour tourner ; molette ou + / − pour zoomer.";
  } catch (reason) {
    viewer?.dispose();
    viewer = undefined;
    if (!closed) showError(reason instanceof Error ? reason.message : "Le chargement a échoué.");
  } finally {
    clearTimeout(timeout);
    busy = false;
    if (!closed) load.disabled = ping.disabled = false;
  }
});

reset.addEventListener("click", () => { viewer?.reset(); focus.value = ""; canvas.focus(); });
focus.addEventListener("change", () => viewer?.focus(focus.value));
for (const layer of ["stars", "signs", "boundaries"] as const) {
  const checkbox = element(layer, HTMLInputElement);
  checkbox.addEventListener("change", () => viewer?.setLayer(layer, checkbox.checked));
}
ping.addEventListener("click", async () => {
  ping.disabled = true;
  error.hidden = true;
  try {
    await connect();
    await bridge.call("zodiac_widget_ping", config.id);
    status.textContent = "Connexion Teams / agent établie.";
  } catch (reason) { showError(reason instanceof Error ? reason.message : "Connexion impossible."); }
  finally { if (!closed) ping.disabled = false; }
});
fullscreen.addEventListener("click", async () => {
  fullscreen.disabled = true;
  try {
    await bridge.displayMode(full ? "inline" : "fullscreen");
    hostContext({ displayMode: full ? "inline" : "fullscreen" });
  } catch (reason) { showError(reason instanceof Error ? reason.message : "Agrandissement impossible."); }
  finally { if (!closed) fullscreen.disabled = !fullscreenSupported; }
});
window.addEventListener("pagehide", () => {
  closed = true;
  controller?.abort();
  observer.disconnect();
  viewer?.dispose();
  bridge.dispose();
});
connect().then(() => { status.textContent = "Prêt. Chargez la vue astronomique."; })
  .catch((reason: unknown) => showError(reason instanceof Error ? reason.message : "Connexion à Teams impossible."));

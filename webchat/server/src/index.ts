import express from "express";
import path from "node:path";
import { z } from "zod";
import { listArtifacts, readArtifact } from "./artifacts.js";
import { config } from "./config.js";
import { browserKey, conversationId, conversationScope, isObject, renderId } from "./security.js";
import { rememberResponse, resetConversation, upstream } from "./upstream.js";

const app = express();
const busy = new Set<string>();
app.disable("x-powered-by");
app.use(express.json({ limit: "32kb" }));
app.use("/api", (req, res, next) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "POST" && req.headers.origin !== config.CLIENT_ORIGIN) {
    res.status(403).json({ error: "Origine du navigateur refusee." });
    return;
  }
  next();
});

function scopeFor(req: express.Request, res: express.Response, id: unknown): string {
  return conversationScope(browserKey(req, res), conversationId.parse(id));
}

app.get("/api/health", (req, res) => {
  browserKey(req, res);
  res.json({ mode: config.AGENT_MODE, model: config.model, agent: config.AGENT_NAME });
});

app.get("/api/renders", async (req, res, next) => {
  try { res.json(await listArtifacts(scopeFor(req, res, req.query.conversation_id))); }
  catch (error) { next(error); }
});

app.get("/api/renders/:id/:file", async (req, res, next) => {
  try {
    const files: Record<string, [string, string]> = {
      data: ["data.json", "application/json"],
      html: ["chart.html", "text/html; charset=utf-8"],
      source: ["source.txt", "text/plain; charset=utf-8"],
    };
    const file = files[req.params.file];
    if (!file) { res.status(404).json({ error: "Artefact inconnu." }); return; }
    const id = renderId.parse(req.params.id);
    const scope = scopeFor(req, res, req.query.conversation_id);
    const data = await readArtifact(scope, id, file[0]);
    res.type(file[1]).setHeader("X-Content-Type-Options", "nosniff");
    if (req.params.file !== "data") res.attachment(`aistro-${id}.${req.params.file === "html" ? "html" : "txt"}`);
    res.send(data);
  } catch (error) { next(error); }
});

app.post("/api/reset", async (req, res, next) => {
  try {
    const scope = scopeFor(req, res, req.body.conversation_id);
    if (busy.has(scope)) { res.status(409).json({ error: "Un tour est encore en cours." }); return; }
    await resetConversation(scope);
    res.json({ ok: true });
  } catch (error) { next(error); }
});

app.post("/api/chat", async (req, res, next) => {
  let scope: string | undefined;
  let ownsBusy = false;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const body = z.object({
      conversation_id: conversationId, input: z.string().trim().min(1).max(8000),
    }).strict().parse(req.body);
    scope = scopeFor(req, res, body.conversation_id);
    if (busy.has(scope)) { res.status(409).json({ error: "Un tour est deja en cours." }); return; }
    busy.add(scope);
    ownsBusy = true;
    res.on("close", () => { if (!res.writableEnded) controller.abort(); });
    const response = await upstream(body.input, scope, controller.signal);
    if (!response.ok || !response.body) {
      throw new Error(`L'agent a refuse la requete (HTTP ${response.status}).`);
    }
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("X-Accel-Buffering", "no");
    res.flushHeaders();
    const decoder = new TextDecoder();
    let buffer = "";
    for await (const chunk of response.body) {
      buffer += decoder.decode(chunk, { stream: true });
      let separator: RegExpExecArray | null;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
          .map(line => line.slice(5).trimStart()).join("\n");
        if (data && data !== "[DONE]") rememberResponse(scope, JSON.parse(data));
      }
      if (buffer.length > 512 * 1024) throw new Error("Agent event exceeds the size limit.");
      if (!res.write(Buffer.from(chunk))) {
        await new Promise<void>(resolve => {
          const resume = () => {
            res.off("drain", resume); res.off("close", resume); resolve();
          };
          res.once("drain", resume); res.once("close", resume);
        });
      }
    }
    res.end();
  } catch (error) {
    if (res.headersSent) {
      console.error("Agent stream failed:", error instanceof Error ? error.name : "UnknownError");
      if (!res.destroyed) {
        res.write(`event: error\ndata: ${JSON.stringify({ error: "Le flux de l'agent a ete interrompu. Reessayez." })}\n\n`);
        res.end();
      }
    } else next(error);
  } finally {
    clearTimeout(timeout);
    if (scope && ownsBusy) busy.delete(scope);
  }
});

app.use("/teams-widget/v1", (req, res, next) => {
  if (config.widgetOrigin && req.headers.origin === config.widgetOrigin) {
    res.setHeader("Access-Control-Allow-Origin", config.widgetOrigin);
    res.setHeader("Vary", "Origin");
  }
  next();
}, express.static(path.join(config.clientDist, "teams-widget/v1")));
app.use(express.static(config.clientDist));
app.get("/", (_req, res) => { res.sendFile(path.join(config.clientDist, "index.html")); });

app.use((error: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  console.error("Web chat request failed:", error instanceof Error ? error.name : "UnknownError");
  const missing = isObject(error) && (error.code === "ENOENT" || error.statusCode === 404);
  const invalid = error instanceof z.ZodError
    || (isObject(error) && (error.status === 400 || error.status === 413));
  res.status(invalid ? (isObject(error) && error.status === 413 ? 413 : 400) : missing ? 404 : 502).json({
    error: invalid ? "Requete invalide ou trop volumineuse."
      : missing ? "Ce rendu est indisponible dans cette conversation."
        : "La requete a echoue. Verifiez l'agent, les identifiants Azure et le stockage.",
  });
});

app.listen(config.PORT, "127.0.0.1", () => {
  console.log(`AIstro proxy: http://127.0.0.1:${config.PORT} (demonstration locale uniquement)`);
});

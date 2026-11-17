import { createHash } from "node:crypto";
import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [botId, destination] = process.argv.slice(2);
if (!botId || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(botId) || !destination) {
  throw new Error("Usage: node devTools/package_teams_widget.mjs <bot-id> <new-output-directory>");
}
const hash = createHash("sha256").update(`28:${botId.toLowerCase()}`).digest("hex").slice(0, 32);
const origin = `https://${hash}.widget-renderer.usercontent.microsoft`;
const source = fileURLToPath(new URL("../webchat/client/dist/teams-widget/v1/", import.meta.url));
const output = path.resolve(destination);
await mkdir(output);
const assets = path.join(output, "teams-widget/v1");
await mkdir(assets, { recursive: true });
for (const name of ["widget.js", "widget.css", "viewer-licenses.txt"]) {
  await copyFile(path.join(source, name), path.join(assets, name));
}
await writeFile(path.join(output, "staticwebapp.config.json"), JSON.stringify({
  globalHeaders: {
    "Access-Control-Allow-Origin": origin,
    "X-Content-Type-Options": "nosniff",
  },
  mimeTypes: { ".js": "text/javascript", ".css": "text/css" },
}, null, 2));
await writeFile(path.join(output, "index.html"),
  "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><title>AIstro</title>"
  + "<p>Assets publics du widget Teams AIstro. Aucune conversation ni ephemeride privee.</p></html>");
console.log(`Package: ${output}\nTeams renderer origin: ${origin}`);

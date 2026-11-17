import dotenv from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

export const projectRoot = fileURLToPath(new URL("../../../", import.meta.url));
dotenv.config({ path: path.join(projectRoot, "webchat/.env") });
dotenv.config({ path: path.join(projectRoot, ".env") });

const settings = z.object({
  AGENT_MODE: z.enum(["local", "foundry"]).default("local"),
  AGENT_LOCAL_URL: z.string().url().default("http://127.0.0.1:8088"),
  AGENT_NAME: z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$/).default("aistro-agent"),
  CLIENT_ORIGIN: z.string().url().default("http://localhost:5173"),
  PORT: z.coerce.number().int().min(1024).max(65535).default(5174),
  ARTIFACT_STORAGE: z.enum(["local", "blob"]).default("local"),
}).parse(process.env);

const projectEndpoint = process.env.AGENT_FOUNDRY_URL ?? process.env.PROJECT_ENDPOINT ?? "";
if (settings.AGENT_MODE === "foundry" && !projectEndpoint.startsWith("https://")) {
  throw new Error("AGENT_FOUNDRY_URL must be a Foundry HTTPS project endpoint.");
}
if (settings.AGENT_MODE === "foundry" && settings.ARTIFACT_STORAGE !== "blob") {
  throw new Error("Foundry mode requires ARTIFACT_STORAGE=blob shared with the hosted agent.");
}

export const config = {
  ...settings,
  projectEndpoint: projectEndpoint.replace(/\/+$/, ""),
  apiVersion: process.env.AGENT_API_VERSION ?? "v1",
  model: process.env.MODEL_DEPLOYMENT_NAME ?? "gpt-5.4-mini",
  tokenScope: "https://ai.azure.com/.default",
  features: "HostedAgents=V1Preview,AgentEndpoints=V1Preview",
  stateDir: path.resolve(projectRoot, process.env.AISTRO_STATE_DIR ?? ".aistro"),
  storageAccount: process.env.AZURE_STORAGE_ACCOUNT_NAME ?? "",
  storageContainer: process.env.AZURE_STORAGE_CONTAINER_NAME ?? "aistro",
  widgetOrigin: process.env.TEAMS_WIDGET_RENDERER_ORIGIN ?? "",
  clientDist: path.join(projectRoot, "webchat/client/dist"),
};

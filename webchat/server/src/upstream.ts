import { DefaultAzureCredential } from "@azure/identity";
import { config } from "./config.js";
import { isObject } from "./security.js";

interface Session {
  agentSession: string;
  conversation: string;
}

const credential = new DefaultAzureCredential();
const sessions = new Map<string, Promise<Session>>();
const previous = new Map<string, string>();
const base = `${config.projectEndpoint}/agents/${config.AGENT_NAME}`;
const versioned = (url: string) => `${url}?api-version=${encodeURIComponent(config.apiVersion)}`;

async function auth(): Promise<Record<string, string>> {
  const token = await credential.getToken(config.tokenScope);
  return {
    Authorization: `Bearer ${token.token}`, "Content-Type": "application/json",
    "Foundry-Features": config.features,
  };
}

async function jsonRequest(url: string, body?: unknown, extra: Record<string, string> = {}) {
  const response = await fetch(versioned(url), {
    method: body === undefined ? "GET" : "POST",
    headers: { ...await auth(), ...extra },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
  });
  if (!response.ok) throw new Error(`Foundry request failed (HTTP ${response.status}).`);
  const value: unknown = await response.json();
  if (!isObject(value)) throw new Error("Foundry returned an invalid object.");
  return value;
}

async function createSession(scope: string): Promise<Session> {
  const agent = await jsonRequest(base);
  const versions = isObject(agent.versions) ? agent.versions : undefined;
  const latest = versions && isObject(versions.latest) ? versions.latest : undefined;
  if (typeof latest?.version !== "string") throw new Error("Foundry agent has no latest version.");
  const session = await jsonRequest(`${base}/endpoint/sessions`, {
    version_indicator: { type: "version_ref", agent_version: latest.version },
  }, { "x-session-isolation-key": scope });
  const conversation = await jsonRequest(`${base}/endpoint/protocols/openai/conversations`, {
    metadata: { aistro_scope: scope },
  });
  if (typeof session.agent_session_id !== "string" || typeof conversation.id !== "string") {
    throw new Error("Foundry did not return the session and conversation identifiers.");
  }
  return { agentSession: session.agent_session_id, conversation: conversation.id };
}

export async function upstream(input: string, scope: string, signal: AbortSignal): Promise<Response> {
  const payload: Record<string, unknown> = {
    model: config.model, input, stream: true, metadata: { aistro_scope: scope },
  };
  let url = `${config.AGENT_LOCAL_URL.replace(/\/+$/, "")}/responses`;
  let headers: Record<string, string> = {
    "Content-Type": "application/json", Accept: "text/event-stream",
  };
  if (config.AGENT_MODE === "foundry") {
    let pending = sessions.get(scope);
    if (!pending) {
      pending = createSession(scope).catch(error => { sessions.delete(scope); throw error; });
      sessions.set(scope, pending);
    }
    const session = await pending;
    payload.agent_session_id = session.agentSession;
    payload.conversation = session.conversation;
    headers = { ...headers, ...await auth() };
    url = versioned(`${base}/endpoint/protocols/openai/responses`);
  } else {
    payload.agent_session_id = scope;
    if (previous.has(scope)) payload.previous_response_id = previous.get(scope);
  }
  return fetch(url, { method: "POST", headers, body: JSON.stringify(payload), signal });
}

export function rememberResponse(scope: string, event: unknown): void {
  if (!isObject(event) || event.type !== "response.completed" || !isObject(event.response)) return;
  if (typeof event.response.id === "string") previous.set(scope, event.response.id);
}

export async function resetConversation(scope: string): Promise<void> {
  const pending = sessions.get(scope);
  if (pending) {
    const session = await pending;
    const response = await fetch(versioned(
      `${base}/endpoint/sessions/${encodeURIComponent(session.agentSession)}`,
    ), {
      method: "DELETE", headers: { ...await auth(), "x-session-isolation-key": scope },
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(`Could not delete the Foundry session (HTTP ${response.status}).`);
    }
  }
  previous.delete(scope);
  sessions.delete(scope);
}

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { z } from "zod";
import { events, requestJson } from "./api/stream";
import { ScenePanel } from "./ScenePanel";
import { formatInstant, manifestSchema, type Manifest } from "./scene/schema";

interface Message { id: string; role: "user" | "assistant"; text: string }
const initialConversation = () => {
  const value = sessionStorage.getItem("aistro.conversation") ?? crypto.randomUUID();
  sessionStorage.setItem("aistro.conversation", value);
  return value;
};

export function App() {
  const [conversation, setConversation] = useState(initialConversation);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [model, setModel] = useState("");
  const [renders, setRenders] = useState<Manifest[]>([]);
  const [selected, setSelected] = useState("");
  const abort = useRef<AbortController>();
  const bottom = useRef<HTMLDivElement>(null);
  const active = renders.find(item => item.id === selected) ?? renders[0];

  async function refresh() {
    const value = await requestJson(`/api/renders?conversation_id=${encodeURIComponent(conversation)}`);
    const list = z.array(manifestSchema).parse(value);
    setRenders(list);
    if (list[0]) setSelected(list[0].id);
  }

  useEffect(() => {
    let current = true;
    requestJson("/api/health").then(value => {
      const health = z.object({ model: z.string() }).parse(value);
      if (current) { setModel(health.model); return refresh(); }
    }).catch((reason: unknown) => {
      if (current) setError(reason instanceof Error ? reason.message : "Connexion au service impossible.");
    });
    return () => { current = false; abort.current?.abort(); };
  }, [conversation]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "auto" }); }, [messages, busy]);

  async function send(text: string) {
    if (busy || !text.trim()) return;
    setBusy(true);
    setError("");
    setDraft("");
    const id = crypto.randomUUID();
    setMessages(previous => [...previous,
      { id: crypto.randomUUID(), role: "user", text },
      { id, role: "assistant", text: "" },
    ]);
    const controller = new AbortController();
    abort.current = controller;
    try {
      const response = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversation, input: text }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error(`L'agent est indisponible (HTTP ${response.status}).`);
      for await (const event of events(response.body)) {
        if (event.type === "response.output_text.delta" && event.delta) {
          setMessages(previous => previous.map(item =>
            item.id === id ? { ...item, text: item.text + event.delta } : item));
        }
      }
    } catch (reason) {
      setError(controller.signal.aborted ? "Demande interrompue."
        : reason instanceof Error ? reason.message : "La demande a échoué.");
    } finally {
      try { await refresh(); }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Impossible de récupérer les rendus."); }
      setBusy(false);
      abort.current = undefined;
    }
  }

  async function reset() {
    try {
      await requestJson("/api/reset", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversation }),
      });
      const id = crypto.randomUUID();
      sessionStorage.setItem("aistro.conversation", id);
      setMessages([]); setRenders([]); setSelected(""); setError(""); setConversation(id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Réinitialisation impossible."); }
  }

  return <div className="app">
    <header className="app-header">
      <a className="brand" href="/" aria-label="Accueil AIstro"><span>✦</span> AIstro</a>
      <span className="header-caption">EXPLORATEUR DU ZODIAQUE</span>
      <span className="model-badge"><i />Foundry{model && ` · ${model}`}</span>
    </header>
    <main className="workspace">
      <div className="sky-area">
        {active ? <ScenePanel key={active.id} manifest={active} conversation={conversation} />
          : <section className="empty-sky">
            <div className="orbital-mark"><span>✦</span></div>
            <span className="eyebrow">DE LA CONVERSATION À LA CONSTELLATION</span>
            <h1>Une date.<br />Un autre regard sur le ciel.</h1>
            <p>Demandez une date à AIstro. NASA/JPL calcule la position du Soleil ;
              votre sphère céleste prend forme ici, en 3D.</p>
            <div className="empty-facts"><span>12 signes tropicaux</span><span>13 constellations</span>
              <span>163 étoiles</span></div>
          </section>}
      </div>
      <aside className="chat-panel" aria-label="Conversation avec AIstro">
        <div className="chat-heading"><div><h2>Parlons du ciel</h2><p>Votre assistant astronomique</p></div>
          <button className="quiet" disabled={busy} onClick={reset} title="Nouvelle conversation">Nouveau</button>
        </div>
        {renders.length > 0 && <label className="render-history">Rendus de cette conversation
          <select value={active?.id ?? ""} onChange={event => setSelected(event.target.value)}>
            {renders.map(item => <option value={item.id} key={item.id}>{formatInstant(item.instant)}</option>)}
          </select>
        </label>}
        <div className="messages" role="log" aria-live="polite">
          {!messages.length && <div className="welcome">
            <span className="assistant-icon">✦</span>
            <h3>Bienvenue dans AIstro</h3>
            <p>Quelle date souhaitez-vous explorer ? Sans heure précisée, j'utilise midi UTC.</p>
            {["Montre le zodiaque d’aujourd’hui", "Affiche le ciel du 3 décembre 2026",
              "Montre le 21 juin 2027 à 18 h UTC"].map(prompt =>
              <button key={prompt} disabled={busy} onClick={() => send(prompt)}>{prompt}<span>↗</span></button>)}
          </div>}
          {messages.filter(message => message.text).map(message =>
            <article key={message.id} className={`message ${message.role}`}>
              <small>{message.role === "user" ? "VOUS" : "✦ AISTRO"}</small>
              <Markdown components={{
                a: props => <a {...props} target="_blank" rel="noopener noreferrer" />,
              }}>{message.text}</Markdown>
            </article>)}
          {busy && <div className="thinking" role="status"><span />AIstro prépare sa réponse…</div>}
          <div ref={bottom} />
        </div>
        {error && <p className="chat-error" role="alert">{error}</p>}
        <form className="composer" onSubmit={event => { event.preventDefault(); send(draft); }}>
          <label className="sr-only" htmlFor="prompt">Votre demande astronomique</label>
          <textarea id="prompt" rows={3} value={draft} maxLength={8000} disabled={busy}
            placeholder="Par exemple : le 3 décembre 2028 à midi…"
            onChange={event => setDraft(event.target.value)}
            onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault(); send(draft);
              }
            }} />
          <div className="composer-bottom"><small>Éphémérides réelles · aucune date préchargée</small>
            {busy ? <button type="button" onClick={() => abort.current?.abort()}>Arrêter</button>
              : <button type="submit" disabled={!draft.trim()}>Envoyer ↑</button>}
          </div>
        </form>
      </aside>
    </main>
  </div>;
}

"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, ChevronRight, Database, LogIn, RotateCcw, Send, Square, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ArcaSpan } from "@/lib/arca-api";
import { cn } from "@/lib/utils";
import { arcaPseudonymize, arcaRetranslate } from "./actions";
import { Highlighted, tokenSpans } from "./highlighted";

/** Ereignisse des Arca-Chat-Servers (arca/terminal/server.mjs). */
type ServerEvent =
  | { type: "auth"; loggedIn: boolean; method?: string | null }
  | { type: "ready"; mcp: string }
  | { type: "login"; url: string | null }
  | { type: "login_done"; ok: boolean; message: string | null }
  | { type: "sent"; text: string; hints: string[] }
  | { type: "assistant"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; content: string; isError: boolean }
  | { type: "done"; ok: boolean; durationMs: number | null; turns: number | null; error: string | null }
  | { type: "error"; text: string }
  | { type: "locked" }
  | { type: "reset" };

type Item =
  | { kind: "user"; original: string; sent?: string; hints?: string[] }
  | { kind: "assistant"; text: string; plain?: { text: string; spans: ArcaSpan[] } | null }
  | { kind: "tool"; id: string; name: string; input: Record<string, unknown>; result?: string; isError?: boolean }
  | { kind: "note"; text: string; tone: "error" | "info" };

/** Relative URLs ("/arca/terminal") nutzen den Host des Dashboards: wss:// hinter HTTPS, das Session-Cookie geht mit. */
function resolve(url: string): string {
  if (/^wss?:\/\//.test(url)) return url;
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${url}`;
}

function pretty(text: string): string {
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}

function toolSummary(item: Extract<Item, { kind: "tool" }>): string {
  if (typeof item.input.sql === "string") return item.input.sql;
  if (typeof item.input.table === "string") return item.input.table;
  return Object.keys(item.input).length ? JSON.stringify(item.input) : "";
}

function rowCount(result?: string): string | null {
  try {
    const r = JSON.parse(result ?? "");
    if (Array.isArray(r.rows)) return `${r.rows.length} Zeile(n)${r.truncated ? ", gekürzt" : ""}`;
    if (Array.isArray(r.tables)) return `${r.tables.length} Tabelle(n)`;
    if (r.error) return "abgelehnt";
  } catch { /* kein JSON */ }
  return null;
}

function ToolCard({ item }: { item: Extract<Item, { kind: "tool" }> }) {
  const count = rowCount(item.result);
  return (
    <details className="border-border bg-card group rounded-md border text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
        <Database className="text-dark-violet h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="font-medium">Tool: {item.name}</span>
        <code className="text-muted-foreground truncate font-mono">{toolSummary(item)}</code>
        <span className={cn("ml-auto shrink-0", item.isError ? "text-dark-red" : "text-muted-foreground")}>
          {item.result === undefined ? "läuft …" : item.isError ? "Fehler" : count ?? "fertig"}
        </span>
      </summary>
      <div className="space-y-2 border-t px-3 py-2">
        <div>
          <p className="text-muted-foreground mb-1">Eingabe (von Claude)</p>
          <pre className="bg-muted overflow-x-auto rounded p-2 font-mono whitespace-pre-wrap">{JSON.stringify(item.input, null, 2)}</pre>
        </div>
        {item.result !== undefined && (
          <div>
            <p className="text-muted-foreground mb-1">Ergebnis (aus visible.db, so an Claude gegeben)</p>
            <pre className="bg-muted max-h-72 overflow-auto rounded p-2 font-mono whitespace-pre-wrap">{pretty(item.result)}</pre>
          </div>
        )}
      </div>
    </details>
  );
}

function AssistantBubble({ item, onToggle }: { item: Extract<Item, { kind: "assistant" }>; onToggle: () => void }) {
  const shown = item.plain ?? { text: item.text, spans: tokenSpans(item.text) };
  return (
    <div className="flex gap-2">
      <Bot className="text-muted-foreground mt-1 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="bg-muted rounded-lg px-3 py-2 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">
          <Highlighted value={shown.text} spans={shown.spans} markdown />
        </div>
        {tokenSpans(item.text).length > 0 && (
          <button type="button" onClick={onToggle} className="text-link hover:text-link-hover mt-1 text-xs">
            {item.plain ? "Tokens anzeigen (wie von Claude)" : "Klarnamen anzeigen (nur hier, lokal)"}
          </button>
        )}
      </div>
    </div>
  );
}

export function Chat({ url }: { url: string }) {
  const socket = useRef<WebSocket | null>(null);
  const list = useRef<HTMLDivElement | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [connected, setConnected] = useState(false);
  const [auth, setAuth] = useState<{ loggedIn: boolean } | null>(null);
  const [mcp, setMcp] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [login, setLogin] = useState<{ url: string | null; started: boolean; message?: string | null } | null>(null);
  const [code, setCode] = useState("");
  const [input, setInput] = useState("");
  const [preview, setPreview] = useState<{ source: string; text: string; spans: ArcaSpan[]; hints: string[] } | null>(null);
  const [closed, setClosed] = useState<string | null>(null);

  const push = (item: Item) => setItems(xs => [...xs, item]);
  const send = (msg: object) => {
    const ws = socket.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  useEffect(() => {
    const ws = new WebSocket(resolve(url));
    socket.current = ws;
    ws.onopen = () => { setConnected(true); setClosed(null); };
    ws.onmessage = e => {
      let ev: ServerEvent;
      try { ev = JSON.parse(String(e.data)); } catch { return; }
      switch (ev.type) {
        case "auth": setAuth({ loggedIn: ev.loggedIn }); if (ev.loggedIn) setLogin(null); break;
        case "ready": setMcp(ev.mcp); break;
        case "login": setLogin({ url: ev.url, started: true }); break;
        case "login_done":
          setLogin(ev.ok ? null : { url: null, started: false, message: ev.message ?? "Anmeldung nicht abgeschlossen." });
          break;
        case "sent":
          setItems(xs => {
            let i = xs.length - 1;
            while (i >= 0 && !(xs[i]!.kind === "user" && (xs[i] as Extract<Item, { kind: "user" }>).sent === undefined)) i--;
            if (i < 0) return xs;
            const copy = [...xs];
            copy[i] = { ...(copy[i] as Extract<Item, { kind: "user" }>), sent: ev.text, hints: ev.hints };
            return copy;
          });
          break;
        case "assistant": push({ kind: "assistant", text: ev.text }); break;
        case "tool_use": push({ kind: "tool", id: ev.id, name: ev.name, input: ev.input }); break;
        case "tool_result":
          setItems(xs => xs.map(x => (x.kind === "tool" && x.id === ev.id ? { ...x, result: ev.content, isError: ev.isError } : x)));
          break;
        case "done":
          setBusy(false);
          if (!ev.ok && ev.error) push({ kind: "note", text: ev.error, tone: "error" });
          else if (ev.durationMs != null) push({ kind: "note", text: `fertig in ${(ev.durationMs / 1000).toFixed(1).replace(".", ",")} s`, tone: "info" });
          break;
        case "error": setBusy(false); push({ kind: "note", text: ev.text, tone: "error" }); break;
        case "reset": setItems([]); setBusy(false); break;
        case "locked": setClosed("Freigabe widerrufen oder noch nicht erteilt. Erst freigeben."); break;
      }
    };
    ws.onclose = e => {
      setConnected(false);
      setBusy(false);
      if (e.code === 4003) setClosed("Nicht angemeldet. Seite neu laden und einloggen.");
      else if (e.code !== 4001) setClosed(c => c ?? "Verbindung zum Chat-Server getrennt. Seite neu laden.");
    };
    ws.onerror = () => setClosed("Chat-Server nicht erreichbar.");
    return () => { ws.close(); socket.current = null; };
  }, [url]);

  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight }); }, [items]);

  // Live-Vorschau: so, wie der Chat-Server die Frage pseudonymisiert an Claude gibt.
  useEffect(() => {
    const text = input;
    if (!text.trim()) { setPreview(null); return; }
    const timer = setTimeout(async () => {
      const r = await arcaPseudonymize(text);
      if (r.ok) setPreview({ source: text, ...r.data });
    }, 400);
    return () => clearTimeout(timer);
  }, [input]);

  const ask = () => {
    const text = input.trim();
    if (!text || busy || !connected || !auth?.loggedIn) return;
    push({ kind: "user", original: text });
    send({ type: "chat", text });
    setBusy(true);
    setInput("");
    setPreview(null);
  };

  const toggle = async (index: number) => {
    const item = items[index];
    if (item?.kind !== "assistant") return;
    if (item.plain) {
      setItems(xs => xs.map((x, i) => (i === index ? { ...item, plain: null } : x)));
      return;
    }
    const r = await arcaRetranslate(item.text);
    if (!r.ok) return push({ kind: "note", text: r.error, tone: "error" });
    const spans = r.data.spans.map(s => ({ start: s.start, end: s.end, type: "restored" }));
    setItems(xs => xs.map((x, i) => (i === index ? { ...item, plain: { text: r.data.text, spans } } : x)));
  };

  const loggedOut = auth && !auth.loggedIn;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={cn("rounded-md px-2 py-0.5", connected ? "bg-light-green text-dark-green" : "bg-muted text-muted-foreground")}>
          {connected ? "verbunden" : "nicht verbunden"}
        </span>
        {auth && (
          <span className={cn("rounded-md px-2 py-0.5", auth.loggedIn ? "bg-light-green text-dark-green" : "bg-light-yellow text-dark-yellow")}>
            {auth.loggedIn ? "bei Claude angemeldet" : "bei Claude nicht angemeldet"}
          </span>
        )}
        {mcp && <span className="bg-muted text-muted-foreground rounded-md px-2 py-0.5">Arca-Daten: {mcp === "connected" ? "verbunden" : mcp}</span>}
        <span className="text-muted-foreground">Claude sieht nur visible.db (nur SELECT), keine weiteren Werkzeuge.</span>
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => send({ type: "reset" })} disabled={!connected || busy}>
          <RotateCcw className="mr-1 h-3.5 w-3.5" aria-hidden />Neues Gespräch
        </Button>
      </div>

      {closed && <p className="bg-light-yellow text-dark-yellow rounded-md px-3 py-2 text-xs">{closed}</p>}

      {loggedOut && (
        <div className="border-dark-blue bg-light-blue/40 space-y-2 rounded-md border p-3 text-xs">
          <p className="font-medium">Mit deinem eigenen Claude-Konto anmelden (einmalig)</p>
          {!login?.started ? (
            <>
              <Button size="sm" onClick={() => { setLogin({ url: null, started: true }); send({ type: "login_start" }); }}>
                <LogIn className="mr-1 h-3.5 w-3.5" aria-hidden />Anmeldung starten
              </Button>
              {login?.message && <p className="text-dark-red">{login.message}</p>}
            </>
          ) : (
            <>
              <p>
                1.{" "}
                {login.url
                  ? <a href={login.url} target="_blank" rel="noopener noreferrer" className="text-link hover:text-link-hover underline">Anmeldeseite öffnen</a>
                  : "Anmeldeseite wird vorbereitet …"}
                , anmelden und den angezeigten Code kopieren.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <span>2.</span>
                <input value={code} onChange={e => setCode(e.target.value)} placeholder="Code hier einfügen" autoComplete="off"
                       spellCheck={false} className="border-input bg-background h-8 min-w-[18rem] flex-1 rounded-md border px-2 font-mono" />
                <Button size="sm" disabled={!login.url || code.trim().length < 20 || /\s/.test(code.trim())}
                        onClick={() => { send({ type: "auth_code", text: code }); setCode(""); }}>Code senden</Button>
              </div>
              <p className="text-muted-foreground">Jeder neue Anmeldeversuch macht den vorherigen Code ungültig. Die Anmeldung bleibt für dich gespeichert.</p>
            </>
          )}
        </div>
      )}

      <div ref={list} className="bg-background h-[28rem] space-y-3 overflow-y-auto rounded-md border p-3" aria-live="polite">
        {!items.length && (
          <p className="text-muted-foreground py-12 text-center text-sm">
            Frag Claude etwas zu den freigegebenen Daten, z. B. „Welche Mandate haben einen Streitwert über 1 Mio. €?“
          </p>
        )}
        {items.map((item, i) => {
          if (item.kind === "user") return (
            <div key={i} className="flex justify-end gap-2">
              <div className="max-w-[80%] space-y-1">
                <div className="bg-light-blue/50 rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">{item.original}</div>
                <p className="text-muted-foreground text-right text-xs">
                  {item.sent === undefined ? "wird pseudonymisiert …" : (
                    <>An Claude gesendet: <span className="font-mono"><Highlighted value={item.sent} spans={tokenSpans(item.sent)} /></span>
                      {item.hints?.length ? <span className="text-dark-yellow"> · Prüfhinweis: {item.hints.join(", ")}</span> : null}</>
                  )}
                </p>
              </div>
              <User className="text-muted-foreground mt-1 h-4 w-4 shrink-0" aria-hidden />
            </div>
          );
          if (item.kind === "tool") return <div key={i} className="pl-6"><ToolCard item={item} /></div>;
          if (item.kind === "assistant") return <AssistantBubble key={i} item={item} onToggle={() => toggle(i)} />;
          return (
            <p key={i} className={cn("pl-6 text-xs", item.tone === "error" ? "text-dark-red" : "text-muted-foreground")}>{item.text}</p>
          );
        })}
        {busy && <p className="text-muted-foreground pl-6 text-xs">Claude arbeitet …</p>}
      </div>

      <div className="space-y-2">
        <textarea value={input} onChange={e => setInput(e.target.value)} rows={3}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(); } }}
                  disabled={!connected || !!loggedOut}
                  placeholder={loggedOut ? "Erst bei Claude anmelden" : "Frage an Claude, gern mit Klarnamen. Enter sendet, Umschalt+Enter neue Zeile."}
                  className="border-input bg-background w-full rounded-md border p-2 text-sm disabled:opacity-60" />
        <div className="flex flex-wrap items-center gap-2">
          {busy ? (
            <Button size="sm" variant="destructive-secondary" onClick={() => send({ type: "stop" })}>
              <Square className="mr-1 h-3.5 w-3.5" aria-hidden />Stopp
            </Button>
          ) : (
            <Button size="sm" onClick={ask} disabled={!input.trim() || !connected || !auth?.loggedIn}>
              <Send className="mr-1 h-3.5 w-3.5" aria-hidden />Senden
            </Button>
          )}
          {preview && preview.source === input && (
            <span className="text-muted-foreground min-w-0 flex-1 text-xs">
              Claude bekommt: <span className="font-mono"><Highlighted value={preview.text} spans={preview.spans} /></span>
              {preview.hints.length > 0 && <span className="text-dark-yellow"> · Prüfhinweis: {preview.hints.join(", ")}</span>}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

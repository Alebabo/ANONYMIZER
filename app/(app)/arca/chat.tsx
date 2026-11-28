"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, ChevronRight, Database, LogIn, RotateCcw, Square, Table2 } from "lucide-react";
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

/** Tabellen, die ein Tool-Aufruf liest: aus dem SQL (FROM/JOIN), aus "table" oder aus dem Ergebnis von list_tables. */
export function toolTables(name: string, input: Record<string, unknown>, result?: string): string[] {
  const out = new Set<string>();
  if (typeof input.table === "string") out.add(input.table);
  if (typeof input.sql === "string") {
    for (const m of input.sql.matchAll(/\b(?:from|join)\s+["`\[]?([A-Za-z_][\w]*)/gi)) {
      if (!/^(pragma_|sqlite_|select$)/i.test(m[1]!)) out.add(m[1]!);
    }
  }
  if (name === "list_tables") {
    try { for (const t of JSON.parse(result ?? "").tables ?? []) out.add(String(t)); } catch { /* kein JSON */ }
  }
  return [...out];
}

function toolFacts(item: Extract<Item, { kind: "tool" }>): { columns: string[]; rows: number | null; truncated: boolean; error: string | null } {
  try {
    const r = JSON.parse(item.result ?? "");
    return {
      columns: Array.isArray(r.columns) ? r.columns.map(String).filter((c: string) => c !== "zeile") : [],
      rows: Array.isArray(r.rows) ? r.rows.length : typeof r.rows === "number" ? r.rows : null,
      truncated: !!r.truncated,
      error: typeof r.error === "string" ? r.error : null,
    };
  } catch {
    return { columns: [], rows: null, truncated: false, error: null };
  }
}

const TOOL_LABEL: Record<string, string> = {
  list_tables: "Tabellen aufgelistet", describe_table: "Tabelle angesehen", query: "Daten abgefragt",
};

function ToolCard({ item }: { item: Extract<Item, { kind: "tool" }> }) {
  const tables = toolTables(item.name, item.input, item.result);
  const facts = toolFacts(item);
  const failed = item.isError || !!facts.error;
  const status = item.result === undefined ? "läuft …"
    : failed ? "abgelehnt"
    : facts.rows != null ? `${facts.rows} Zeile(n)${facts.truncated ? ", gekürzt" : ""}` : "fertig";
  return (
    <details className="group text-xs">
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 py-0.5">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
        <Database className="text-dark-violet h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>{TOOL_LABEL[item.name] ?? item.name}</span>
        {tables.map(t => (
          <span key={t} className="bg-muted text-foreground inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono">
            <Table2 className="h-3 w-3" aria-hidden />{t}
          </span>
        ))}
        {facts.columns.length > 0 && <span>· Spalten: {facts.columns.join(", ")}</span>}
        <span className={cn(failed && "text-dark-red")}>· {status}</span>
      </summary>
      <div className="border-border mt-1 ml-5 space-y-2 border-l pl-3">
        {typeof item.input.sql === "string" ? (
          <div>
            <p className="text-muted-foreground mb-1">SQL von Claude</p>
            <pre className="bg-muted overflow-x-auto rounded-md p-2 font-mono whitespace-pre-wrap">{item.input.sql}</pre>
          </div>
        ) : Object.keys(item.input).length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1">Eingabe von Claude</p>
            <pre className="bg-muted overflow-x-auto rounded-md p-2 font-mono whitespace-pre-wrap">{JSON.stringify(item.input, null, 2)}</pre>
          </div>
        )}
        {item.result !== undefined && (
          <div>
            <p className="text-muted-foreground mb-1">Ergebnis aus visible.db (so hat Claude es bekommen)</p>
            <ResultView text={item.result} />
          </div>
        )}
      </div>
    </details>
  );
}

/** Abfrageergebnis als schlichte Tabelle; alles andere als JSON. */
function ResultView({ text }: { text: string }) {
  let data: { columns?: unknown; rows?: unknown } | null = null;
  try { data = JSON.parse(text); } catch { /* kein JSON */ }
  if (data && Array.isArray(data.columns) && Array.isArray(data.rows)) {
    const cols = data.columns.map(String);
    const rows = data.rows as unknown[][];
    const cell = "border-border border px-1.5 py-0.5 text-left align-top font-normal whitespace-nowrap";
    return (
      <div className="border-border max-h-72 overflow-auto border">
        <table className="w-max min-w-full border-collapse font-mono text-xs">
          <thead className="bg-muted sticky top-0"><tr>{cols.map((c, i) => <th key={i} className={cell}>{c}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{r.map((v, j) => (
                <td key={j} title={String(v ?? "")} className={cn(cell, "max-w-[20rem] overflow-hidden text-ellipsis")}>{String(v ?? "")}</td>
              ))}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <pre className="bg-muted max-h-72 overflow-auto rounded-md p-2 font-mono whitespace-pre-wrap">{pretty(text)}</pre>;
}

function AssistantMessage({ item, onToggle }: { item: Extract<Item, { kind: "assistant" }>; onToggle: () => void }) {
  const shown = item.plain ?? { text: item.text, spans: tokenSpans(item.text) };
  return (
    <div className="text-[15px] leading-7">
      <div className="whitespace-pre-wrap [overflow-wrap:anywhere]">
        <Highlighted value={shown.text} spans={shown.spans} markdown />
      </div>
      {tokenSpans(item.text).length > 0 && (
        <button type="button" onClick={onToggle} className="text-muted-foreground hover:text-foreground mt-1 text-xs underline-offset-2 hover:underline">
          {item.plain ? "Tokens anzeigen (wie von Claude)" : "Klarnamen anzeigen (nur hier, lokal)"}
        </button>
      )}
    </div>
  );
}

export function Chat({ url, suggestions = [] }: { url: string; suggestions?: string[] }) {
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

  const ask = (preset?: string) => {
    const text = (preset ?? input).trim();
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
  const canSend = connected && !!auth?.loggedIn && !busy;
  const dot = (ok: boolean) => <span className={cn("inline-block h-1.5 w-1.5 rounded-full", ok ? "bg-dark-green" : "bg-dark-yellow")} />;
  return (
    <div className="flex h-full min-h-[30rem] flex-col">
      <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 px-1 pb-2 text-xs">
        <span className="inline-flex items-center gap-1.5">{dot(connected)}{connected ? "verbunden" : "nicht verbunden"}</span>
        {auth && <span className="inline-flex items-center gap-1.5">{dot(auth.loggedIn)}{auth.loggedIn ? "bei Claude angemeldet" : "nicht angemeldet"}</span>}
        {mcp && <span className="inline-flex items-center gap-1.5">{dot(mcp === "connected")}Arca-Daten {mcp === "connected" ? "verbunden" : mcp}</span>}
        <button type="button" onClick={() => send({ type: "reset" })} disabled={!connected || busy}
                className="hover:text-foreground ml-auto inline-flex items-center gap-1 disabled:opacity-50">
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />Neues Gespräch
        </button>
      </div>

      <div ref={list} className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
        <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
          {closed && <p className="bg-light-yellow text-dark-yellow rounded-xl px-3 py-2 text-xs">{closed}</p>}

          {loggedOut && (
            <div className="border-border space-y-2 rounded-2xl border p-4 text-sm">
              <p className="font-medium">Mit deinem eigenen Claude-Konto anmelden (einmalig)</p>
              {!login?.started ? (
                <>
                  <Button size="sm" onClick={() => { setLogin({ url: null, started: true }); send({ type: "login_start" }); }}>
                    <LogIn className="mr-1 h-3.5 w-3.5" aria-hidden />Anmeldung starten
                  </Button>
                  {login?.message && <p className="text-dark-red text-xs">{login.message}</p>}
                </>
              ) : (
                <>
                  <p className="text-xs">
                    1.{" "}
                    {login.url
                      ? <a href={login.url} target="_blank" rel="noopener noreferrer" className="text-link hover:text-link-hover underline">Anmeldeseite öffnen</a>
                      : "Anmeldeseite wird vorbereitet …"}
                    , anmelden und den angezeigten Code kopieren.
                  </p>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span>2.</span>
                    <input value={code} onChange={e => setCode(e.target.value)} placeholder="Code hier einfügen" autoComplete="off"
                           spellCheck={false} className="border-input bg-background h-8 min-w-[14rem] flex-1 rounded-lg border px-2 font-mono" />
                    <Button size="sm" disabled={!login.url || code.trim().length < 20 || /\s/.test(code.trim())}
                            onClick={() => { send({ type: "auth_code", text: code }); setCode(""); }}>Code senden</Button>
                  </div>
                  <p className="text-muted-foreground text-xs">Jeder neue Anmeldeversuch macht den vorherigen Code ungültig. Die Anmeldung bleibt für dich gespeichert.</p>
                </>
              )}
            </div>
          )}

          {!items.length && !loggedOut && (
            <div className="space-y-6 pt-[8vh] text-center">
              <h2 className="text-2xl font-medium">Was möchtest du über die freigegebenen Mandate wissen?</h2>
              <p className="text-muted-foreground text-sm">Namen darfst du normal schreiben. Claude bekommt sie nur als Tokens und sieht ausschließlich Tabelle A.</p>
              {suggestions.length > 0 && (
                <div className="grid gap-2 text-left sm:grid-cols-3" aria-label="Fragevorschläge">
                  {suggestions.map(q => (
                    <button key={q} type="button" onClick={() => ask(q)} disabled={!canSend}
                            className="border-border hover:bg-muted rounded-2xl border p-3 text-sm disabled:cursor-not-allowed disabled:opacity-50">
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {items.map((item, i) => {
            if (item.kind === "user") return (
              <div key={i} className="flex flex-col items-end gap-1">
                <div className="bg-muted max-w-[85%] rounded-3xl px-4 py-2.5 text-[15px] whitespace-pre-wrap">{item.original}</div>
                <p className="text-muted-foreground max-w-[85%] text-right text-xs">
                  {item.sent === undefined ? "wird pseudonymisiert …" : (
                    <>an Claude: <span className="font-mono"><Highlighted value={item.sent} spans={tokenSpans(item.sent)} /></span>
                      {item.hints?.length ? <span className="text-dark-yellow"> · Prüfhinweis: {item.hints.join(", ")}</span> : null}</>
                  )}
                </p>
              </div>
            );
            if (item.kind === "tool") return <ToolCard key={i} item={item} />;
            if (item.kind === "assistant") return <AssistantMessage key={i} item={item} onToggle={() => toggle(i)} />;
            return <p key={i} className={cn("text-xs", item.tone === "error" ? "text-dark-red" : "text-muted-foreground")}>{item.text}</p>;
          })}
          {busy && <p className="text-muted-foreground animate-pulse text-sm">Claude denkt nach …</p>}
        </div>
      </div>

      <div className="mx-auto w-full max-w-3xl px-4 pt-2">
        {items.length > 0 && suggestions.length > 0 && !busy && (
          <div className="mb-2 flex gap-1.5 overflow-x-auto" aria-label="Fragevorschläge">
            {suggestions.map(q => (
              <button key={q} type="button" onClick={() => ask(q)} disabled={!canSend}
                      className="border-border hover:bg-muted shrink-0 rounded-full border px-3 py-1 text-xs disabled:opacity-50">{q}</button>
            ))}
          </div>
        )}
        <div className="border-border bg-background focus-within:border-border-contrast flex items-end gap-2 rounded-3xl border px-4 py-2 shadow-sm">
          <textarea value={input} onChange={e => setInput(e.target.value)} rows={1}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(); } }}
                    disabled={!connected || !!loggedOut}
                    placeholder={loggedOut ? "Erst bei Claude anmelden" : "Frage an Claude …"}
                    className="field-sizing-content max-h-48 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none disabled:opacity-60" />
          {busy ? (
            <button type="button" onClick={() => send({ type: "stop" })} aria-label="Stopp"
                    className="bg-foreground text-background mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
              <Square className="h-3.5 w-3.5" aria-hidden />
            </button>
          ) : (
            <button type="button" onClick={() => ask()} disabled={!input.trim() || !canSend} aria-label="Senden"
                    className="bg-foreground text-background mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full disabled:opacity-30">
              <ArrowUp className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
        <p className="text-muted-foreground min-h-5 px-2 pt-1.5 pb-1 text-xs">
          {preview && preview.source === input ? (
            <>Claude bekommt: <span className="font-mono"><Highlighted value={preview.text} spans={preview.spans} /></span>
              {preview.hints.length > 0 && <span className="text-dark-yellow"> · Prüfhinweis: {preview.hints.join(", ")}</span>}</>
          ) : "Enter sendet, Umschalt+Enter neue Zeile. Claude sieht nur Tabelle A (nur lesend)."}
        </p>
      </div>
    </div>
  );
}

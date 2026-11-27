"use client";
import { useEffect, useImperativeHandle, useRef, type Ref } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

export type TerminalHandle = {
  selection: () => string;
  /** Frage an Claude; der Terminal-Server pseudonymisiert sie, bevor claude sie bekommt. */
  sendPrompt: (text: string) => void;
  unlock: () => void;
  lock: () => void;
};

/** Steuernachrichten des Terminal-Servers (arca/terminal/server.mjs). */
export type TerminalEvent =
  | { mode: "protected" | "direct" }
  | { blocked: true }
  | { sent: string; hints: string[] }
  | { error: string };

const CONTROL_PREFIX = "\u0000arca:";

/** Relative URLs ("/arca/terminal") use the dashboard's host: wss:// behind HTTPS, so the session cookie is sent. */
function resolve(url: string): string {
  if (/^wss?:\/\//.test(url)) return url;
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${url}`;
}

/** xterm.js an den Arca-Terminal-Server. Der Server startet claude erst nach Freigabe. */
export function Terminal({ ref, url, onEvent }: {
  ref?: Ref<TerminalHandle>; url: string; onEvent?: (e: TerminalEvent) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<XTerm | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const events = useRef(onEvent);
  events.current = onEvent;

  const send = (msg: object) => {
    const ws = socket.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };
  useImperativeHandle(ref, () => ({
    selection: () => term.current?.getSelection() ?? "",
    sendPrompt: (text: string) => send({ type: "prompt", text }),
    unlock: () => send({ type: "unlock" }),
    lock: () => send({ type: "lock" }),
  }), []);

  useEffect(() => {
    if (!box.current) return;
    const t = new XTerm({ fontSize: 13, cursorBlink: true, convertEol: false, theme: { background: "#111111" } });
    const fit = new FitAddon();
    t.loadAddon(fit);
    t.open(box.current);
    fit.fit();
    term.current = t;
    const target = resolve(url);
    const ws = new WebSocket(target);
    socket.current = ws;
    ws.onopen = () => send({ type: "resize", cols: t.cols, rows: t.rows });
    ws.onmessage = e => {
      const data = typeof e.data === "string" ? e.data : "";
      if (data.startsWith(CONTROL_PREFIX)) {
        try { events.current?.(JSON.parse(data.slice(CONTROL_PREFIX.length)) as TerminalEvent); } catch { /* ignorieren */ }
        return;
      }
      t.write(data);
    };
    ws.onerror = () => t.write(`\r\n\x1b[31mTerminal-Server nicht erreichbar (${target}).\x1b[0m\r\n`);
    ws.onclose = e => {
      if (e.code === 4001) t.write("\r\n\x1b[33mErst freigeben.\x1b[0m\r\n");
      if (e.code === 4003) t.write("\r\n\x1b[31mNicht angemeldet. Seite neu laden und einloggen.\x1b[0m\r\n");
    };
    const input = t.onData(data => send({ type: "input", data }));
    const onResize = () => { fit.fit(); send({ type: "resize", cols: t.cols, rows: t.rows }); };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      input.dispose();
      ws.close();
      socket.current = null;
      t.dispose();
      term.current = null;
    };
  }, [url]);

  return <div ref={box} className="h-[28rem] w-full overflow-hidden rounded-md bg-[#111111] p-2" />;
}

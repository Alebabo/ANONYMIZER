"use client";
import { useEffect, useImperativeHandle, useRef, type Ref } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

export type TerminalHandle = { selection: () => string };

/** Relative URLs ("/arca/terminal") use the dashboard's host: wss:// behind HTTPS, so the session cookie is sent. */
function resolve(url: string): string {
  if (/^wss?:\/\//.test(url)) return url;
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${url}`;
}

/** xterm.js an den Arca-Terminal-Server (arca/terminal/server.mjs). Der Server startet claude erst nach Freigabe. */
export function Terminal({ ref, url }: { ref?: Ref<TerminalHandle>; url: string }) {
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<XTerm | null>(null);
  useImperativeHandle(ref, () => ({ selection: () => term.current?.getSelection() ?? "" }), []);

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
    const send = (msg: object) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(msg));
    ws.onopen = () => send({ type: "resize", cols: t.cols, rows: t.rows });
    ws.onmessage = e => t.write(typeof e.data === "string" ? e.data : "");
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
      t.dispose();
      term.current = null;
    };
  }, [url]);

  return <div ref={box} className="h-[28rem] w-full overflow-hidden rounded-md bg-[#111111] p-2" />;
}

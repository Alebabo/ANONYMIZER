"use client";
import { useEffect, useImperativeHandle, useRef, type Ref } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

export type TerminalHandle = { selection: () => string };

const URL = process.env.NEXT_PUBLIC_ARCA_TERMINAL_URL || "ws://127.0.0.1:8101";

/** xterm.js an den Arca-Terminal-Server (arca/terminal/server.mjs). Der Server startet claude erst nach Freigabe. */
export function Terminal({ ref }: { ref?: Ref<TerminalHandle> }) {
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
    const ws = new WebSocket(URL);
    const send = (msg: object) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(msg));
    ws.onopen = () => send({ type: "resize", cols: t.cols, rows: t.rows });
    ws.onmessage = e => t.write(typeof e.data === "string" ? e.data : "");
    ws.onerror = () => t.write(`\r\n\x1b[31mTerminal-Server nicht erreichbar (${URL}). Start: npm --prefix arca/terminal start\x1b[0m\r\n`);
    ws.onclose = e => e.code === 4001 && t.write("\r\n\x1b[33mErst freigeben.\x1b[0m\r\n");
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
  }, []);

  return <div ref={box} className="h-[28rem] w-full overflow-hidden rounded-md bg-[#111111] p-2" />;
}

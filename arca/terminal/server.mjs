// Arca-Chat-Server: WebSocket <-> claude-CLI im Stream-Modus (claude -p --input-format/--output-format stream-json).
//
// Kein Terminal mehr: Fragen kommen als {type:"chat"} und werden HIER über den Arca-Service pseudonymisiert
// (/pseudonymize), bevor claude sie bekommt; der Browser kann das nicht umgehen. Was claude zurückgibt (Text,
// Tool-Aufrufe mit Eingaben, Tool-Ergebnisse, Abschluss) geht als strukturierte Ereignisse an den Browser.
//
// Claude bekommt genau einen Zugang zu Daten: den Arca-MCP-Server auf visible.db.
//   --tools ""             keine Built-in-Tools (kein Bash/Read/Edit/WebFetch), sonst könnte Claude vault.db
//                          direkt lesen
//   --strict-mcp-config    keine weiteren MCP-Server aus Nutzer- oder Projektkonfiguration
//   --setting-sources project, cwd = leeres Arbeitsverzeichnis: keine Hooks/Settings aus ~/.claude
//
// Eigenes Abo: jede Person meldet sich einmal mit ihrem eigenen Claude-Konto an ({type:"login_start"} startet
// `claude auth login` in einer PTY; Link und Code laufen über den Chat). Jede angemeldete Dashboard-Person hat
// ein eigenes CLAUDE_CONFIG_DIR. Kein API-Key auf dem Server; ANTHROPIC_* wird aus der Umgebung entfernt.
//
// Login (Dashboard): mit ARCA_AUTH_API_URL muss der WebSocket-Request das Dashboard-Session-Cookie tragen;
// es wird bei der OpenAnonymizer-API geprüft (GET /v1/auth/me). Ohne gültige Sitzung: Code 4003.
// Sperre: nur wenn der Arca-Service "released" meldet; bei Widerruf wird die Sitzung beendet (Code 4001).
// Audit: jede Frage (pseudonymisiert, so wie sie an Claude ging) und jeder Login-Code (ohne Inhalt).
// Origin-Prüfung gegen Cross-Site-WebSocket-Hijacking.

import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import pty from "node-pty";

const here = dirname(fileURLToPath(import.meta.url));
const ARCA = resolve(here, "..");
const PORT = Number(process.env.ARCA_TERMINAL_PORT || 8101);
const HOST = process.env.ARCA_TERMINAL_HOST || "127.0.0.1";
const AUTH_API = process.env.ARCA_AUTH_API_URL || "";
const SESSION_COOKIE = "anonymizer_session";
const SERVICE = process.env.ARCA_SERVICE_URL || "http://127.0.0.1:8100";
const ORIGINS = (process.env.ARCA_ALLOWED_ORIGINS || "http://localhost:3000,http://127.0.0.1:3000").split(",");
const DATA_DIR = resolve(process.env.ARCA_DATA_DIR || join(ARCA, "data"));
const VISIBLE = join(DATA_DIR, "visible.db");
const WORKSPACE = join(ARCA, "workspace");
// Eigenes Konfigurationsverzeichnis je Person; auch lokal nie die globale ~/.claude.json anfassen.
const CLAUDE_HOME = process.env.ARCA_CLAUDE_HOME || join(DATA_DIR, "claude");
const PYTHON = process.env.ARCA_PYTHON || "python3";
const CLAUDE = process.env.ARCA_CLAUDE_BIN || "claude";
const TOOLS = ["mcp__arca__list_tables", "mcp__arca__describe_table", "mcp__arca__query"];
const MAX_QUESTION = 20000;
const MAX_TOOL_RESULT = 20000;

export function mcpConfig() {
  return {
    mcpServers: {
      arca: { type: "stdio", command: PYTHON, args: ["-I", join(ARCA, "mcp", "server.py"), "--db", VISIBLE], env: {} },
    },
  };
}

/** Einschränkungen für claude: nur Arca-MCP, keine Built-in-Tools, keine fremden Settings. */
export function claudeArgs(configPath) {
  return [
    "--strict-mcp-config", "--mcp-config", configPath,
    "--tools", "",
    "--allowedTools", TOOLS.join(","),
    "--setting-sources", "project",
  ];
}

/** Chat-Prozess: Stream-Modus, mehrere Fragen nacheinander im selben Gespräch. */
export function chatArgs(configPath) {
  return ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", ...claudeArgs(configPath)];
}

export function cleanEnv(env = process.env) {
  // ANTHROPIC_*: kein Server-Key, Claude läuft immer mit dem eigenen Abo der Person.
  return Object.fromEntries(Object.entries(env).filter(([k]) => !/^(ARCA_|ANONYMIZER_|ANTHROPIC_)/.test(k)));
}

export function sessionToken(cookieHeader = "") {
  for (const part of cookieHeader.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === SESSION_COOKIE) return decodeURIComponent(v.join("="));
  }
  return null;
}

// Claude-Anmeldung: der OAuth-Code ist ein Token ohne Leerzeichen. Nur so etwas geht ohne Pseudonymisierung durch.
const AUTH_CODE = /^[A-Za-z0-9_\-#.~]{20,512}$/;
export const isAuthCode = text => typeof text === "string" && AUTH_CODE.test(text.trim());

// eslint-disable-next-line no-control-regex
const ANSI = /\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]/g;
// eslint-disable-next-line no-control-regex
const OSC8 = /\x1b\]8;[^;]*;(https:\/\/claude\.ai\/oauth\/authorize\?[^\x07\x1b]+)(?:\x07|\x1b\\)/;
const LOGIN_URL = /https:\/\/claude\.ai\/oauth\/authorize\?\S+/;
// claude setzt Wörter per Cursorposition (ESC[12G) statt mit Leerzeichen: als Leerzeichen lesen.
// eslint-disable-next-line no-control-regex
const CURSOR_MOVE = /\x1b\[\d*[GC]/g;

/** Terminal-Output als lesbaren Text (für die Erkennung, nicht für die Anzeige). */
export const screenText = raw => raw.replace(CURSOR_MOVE, " ").replace(ANSI, "");

/** Erkennt im Output von `claude auth login`, dass der Code erwartet wird, und die Login-URL. */
export class LoginWatch {
  constructor() { this.raw = ""; this.active = false; }

  /** Neuen Output einlesen; liefert {login, url} bei Zustandswechsel, sonst null. */
  feed(chunk) {
    this.raw = (this.raw + chunk).slice(-16000);
    const text = screenText(this.raw);
    if (!this.active && /paste\s+code\s+here/i.test(text)) {
      this.active = true;
      const url = this.raw.match(OSC8)?.[1] ?? text.match(LOGIN_URL)?.[0] ?? null;
      return { login: true, url };
    }
    return null;
  }

  /** Nach dem Senden des Codes: zurücksetzen, damit ein erneutes "Paste code here" (falscher Code) erkannt wird. */
  reset() { this.raw = ""; this.active = false; return { login: false }; }
}

/** Frage für claude, pseudonymisiert durch den Arca-Service (mit denselben Tokens wie in A). */
export async function protectPrompt(text, service = SERVICE) {
  const res = await fetch(`${service}/pseudonymize`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`pseudonymize ${res.status}`);
  const out = await res.json();
  return { text: out.text.trim(), hints: out.hints ?? [] };
}

const clip = (s, n) => (s.length > n ? `${s.slice(0, n)}\n… (${s.length - n} Zeichen gekürzt)` : s);
const shortTool = name => String(name).replace(/^mcp__arca__/, "");

/**
 * Ein Ereignis von `claude --output-format stream-json` in Chat-Ereignisse übersetzen (0..n).
 * Nur was die Oberfläche braucht: Text, Tool-Aufrufe, Tool-Ergebnisse, Abschluss, MCP-Status.
 */
export function mapEvent(e) {
  const out = [];
  if (e?.type === "system" && e.subtype === "init") {
    const arca = (e.mcp_servers ?? []).find(s => s.name === "arca");
    out.push({ type: "ready", mcp: arca?.status ?? "missing" });
  } else if (e?.type === "assistant") {
    for (const c of e.message?.content ?? []) {
      if (c.type === "text" && c.text?.trim()) out.push({ type: "assistant", text: c.text });
      if (c.type === "tool_use") out.push({ type: "tool_use", id: c.id, name: shortTool(c.name), input: c.input ?? {} });
    }
  } else if (e?.type === "user" && Array.isArray(e.message?.content)) {
    for (const c of e.message.content) {
      if (c.type !== "tool_result") continue;
      const content = Array.isArray(c.content)
        ? c.content.map(p => (p.type === "text" ? p.text : `[${p.type}]`)).join("\n")
        : String(c.content ?? "");
      out.push({ type: "tool_result", id: c.tool_use_id, content: clip(content, MAX_TOOL_RESULT), isError: !!c.is_error });
    }
  } else if (e?.type === "result") {
    out.push({
      type: "done", ok: !e.is_error && e.subtype === "success", durationMs: e.duration_ms ?? null,
      turns: e.num_turns ?? null, error: e.is_error ? String(e.result ?? e.subtype ?? "Fehler") : null,
    });
  }
  return out;
}

/** Ereignis ins Audit-Log; false, wenn es nicht geschrieben werden konnte. */
async function auditEvent(action, actor, details) {
  try {
    const res = await fetch(`${SERVICE}/audit`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ action, actor, ...(details ? { details } : {}) }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Dashboard-Person zur Sitzung ({id, email}) oder null. Ohne ARCA_AUTH_API_URL (lokal): "local". */
async function user(req) {
  if (!AUTH_API) return { id: "local", email: "lokal" };
  const token = sessionToken(req.headers.cookie);
  if (!token) return null;
  try {
    const res = await fetch(`${AUTH_API}/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return null;
    const me = await res.json();
    return me?.user?.id ? { id: me.user.id, email: me.user.email ?? me.user.id } : null;
  } catch {
    return null;
  }
}

/**
 * Das Arca-Arbeitsverzeichnis (leer bis auf mcp.json; claude hat keine Datei-Tools) als vertraut markieren.
 * Schreibt nur in die Arca-eigene Konfiguration der Person (CLAUDE_CONFIG_DIR/.claude.json).
 */
export function trustWorkspace(configDir, workspace = WORKSPACE) {
  const file = join(configDir, ".claude.json");
  let cfg = {};
  if (existsSync(file)) {
    try { cfg = JSON.parse(readFileSync(file, "utf8")); } catch { return; }  // fremdes Format: nicht anfassen
  }
  cfg.projects ??= {};
  if (cfg.projects[workspace]?.hasTrustDialogAccepted) return;
  cfg.projects[workspace] = { ...cfg.projects[workspace], hasTrustDialogAccepted: true };
  writeFileSync(file, JSON.stringify(cfg, null, 2), { mode: 0o600 });
}

export function claudeEnv(userId, env = process.env, home = CLAUDE_HOME) {
  const out = cleanEnv(env);
  const dir = join(home, createHash("sha256").update(String(userId)).digest("hex").slice(0, 24));
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  trustWorkspace(dir);
  out.CLAUDE_CONFIG_DIR = dir;
  out.HOME = dir;
  return out;
}

/** Angemeldet? (`claude auth status --json` mit der Konfiguration der Person) */
function authStatus(env) {
  return new Promise(res => {
    execFile(CLAUDE, ["auth", "status", "--json"], { env, timeout: 30000 }, (err, stdout) => {
      try {
        const s = JSON.parse(stdout);
        res({ loggedIn: !!s.loggedIn, method: s.authMethod ?? null });
      } catch {
        res({ loggedIn: false, method: null, error: err ? "Status nicht lesbar" : null });
      }
    });
  });
}

async function released() {
  try {
    const res = await fetch(`${SERVICE}/status`);
    return res.ok && (await res.json()).released === true;
  } catch {
    return false;
  }
}

function prepareWorkspace() {
  mkdirSync(WORKSPACE, { recursive: true });
  const path = join(WORKSPACE, "mcp.json");
  writeFileSync(path, JSON.stringify(mcpConfig(), null, 2));
  return path;
}

function start() {
  const wss = new WebSocketServer({
    host: HOST, port: PORT,
    verifyClient: ({ origin }) => ORIGINS.includes(origin),
  });

  wss.on("connection", async (ws, req) => {
    const send = obj => ws.readyState === ws.OPEN && ws.send(JSON.stringify(obj));
    const who = await user(req);
    if (!who) {
      send({ type: "error", text: "Nicht angemeldet." });
      ws.close(4003, "login required");
      return;
    }
    if (!(await released())) {
      send({ type: "locked" });
      ws.close(4001, "not released");
      return;
    }
    const config = prepareWorkspace();
    const env = claudeEnv(who.id);
    let chat = null;        // laufender claude-Prozess (Gespräch)
    let busy = false;
    let login = null;       // laufendes `claude auth login`
    const loginWatch = new LoginWatch();

    const sendAuth = async () => send({ type: "auth", ...(await authStatus(env)) });

    const stopChat = () => {
      if (chat) { try { chat.kill("SIGTERM"); } catch { /* schon beendet */ } }
      chat = null;
      busy = false;
    };

    const startChat = () => {
      const proc = spawn(CLAUDE, chatArgs(config), { cwd: WORKSPACE, env, stdio: ["pipe", "pipe", "pipe"] });
      let stderr = "";
      proc.stderr.on("data", d => { stderr = (stderr + d).slice(-2000); });
      createInterface({ input: proc.stdout }).on("line", line => {
        let e;
        try { e = JSON.parse(line); } catch { return; }
        for (const ev of mapEvent(e)) {
          if (ev.type === "done") busy = false;
          send(ev);
        }
      });
      proc.on("exit", code => {
        if (chat !== proc) return;
        chat = null;
        if (busy) {
          busy = false;
          const reason = /log ?in|auth|credential|401/i.test(stderr) ? " Bitte bei Claude anmelden." : "";
          send({ type: "done", ok: false, error: `Claude wurde beendet (Code ${code}).${reason}` });
          sendAuth();
        }
      });
      chat = proc;
      return proc;
    };

    const ask = async text => {
      if (busy) return send({ type: "error", text: "Claude antwortet noch. Warten oder Stopp drücken." });
      let safe;
      try {
        safe = await protectPrompt(text);
      } catch {
        return send({ type: "error", text: "Frage konnte nicht pseudonymisiert werden und wurde nicht gesendet." });
      }
      if (!(await auditEvent("chat_message", who.email, { text: safe.text, hints: safe.hints }))) {
        return send({ type: "error", text: "Nicht gesendet: Audit-Log nicht erreichbar." });
      }
      busy = true;
      send({ type: "sent", text: safe.text, hints: safe.hints });
      const proc = chat ?? startChat();
      proc.stdin.write(JSON.stringify({ type: "user", message: { role: "user", content: safe.text } }) + "\n");
    };

    const startLogin = () => {
      if (login) return;
      loginWatch.reset();
      login = pty.spawn(CLAUDE, ["auth", "login", "--claudeai"], {
        name: "xterm-256color", cols: 200, rows: 40, cwd: WORKSPACE, env,
      });
      let tail = "";
      login.onData(d => {
        tail = (tail + d).slice(-4000);
        const change = loginWatch.feed(d);
        if (change?.login) send({ type: "login", url: change.url });
      });
      login.onExit(async ({ exitCode }) => {
        login = null;
        const status = await authStatus(env);
        const msg = screenText(tail).replace(/\s+/g, " ").trim().slice(-300);
        send({ type: "login_done", ok: status.loggedIn, message: status.loggedIn ? null : (msg || `Code ${exitCode}`) });
        send({ type: "auth", ...status });
      });
    };

    const sendCode = async text => {
      if (!login || !loginWatch.active || !isAuthCode(text)) {
        return send({ type: "error", text: "Kein gültiger Login-Code (oder es läuft gerade keine Anmeldung)." });
      }
      if (!(await auditEvent("terminal_login_code", who.email))) {
        return send({ type: "error", text: "Login-Code nicht gesendet: Audit-Log nicht erreichbar." });
      }
      login.write(String(text).trim());
      setTimeout(() => login?.write("\r"), 50);
      loginWatch.reset();
    };

    const watch = setInterval(async () => {
      if (!(await released())) {
        send({ type: "locked" });
        stopChat();
        ws.close(4001, "revoked");
      }
    }, 3000);

    ws.on("message", async raw => {
      let msg;
      try { msg = JSON.parse(String(raw)); } catch { return; }
      if (msg.type === "chat" && typeof msg.text === "string" && msg.text.trim() && msg.text.length <= MAX_QUESTION) await ask(msg.text);
      if (msg.type === "stop") { stopChat(); send({ type: "done", ok: false, error: "Gestoppt. Das nächste Gespräch beginnt neu." }); }
      if (msg.type === "reset") { stopChat(); send({ type: "reset" }); }
      if (msg.type === "login_start") startLogin();
      if (msg.type === "auth_code") await sendCode(msg.text);
      if (msg.type === "auth_status") await sendAuth();
    });
    ws.on("close", () => {
      clearInterval(watch);
      stopChat();
      if (login) { try { login.kill(); } catch { /* schon beendet */ } }
    });

    await sendAuth();
  });

  console.log(`Arca-Chat auf ws://${HOST}:${PORT} (Login: ${AUTH_API ? "Dashboard-Sitzung" : "aus"}) (Service ${SERVICE}, Origins ${ORIGINS.join(", ")})`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) start();

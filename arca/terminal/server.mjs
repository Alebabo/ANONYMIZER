// Arca-Terminal: WebSocket <-> node-pty, in dem die claude-CLI läuft.
//
// Claude bekommt genau einen Zugang zu Daten: den Arca-MCP-Server auf visible.db.
//   --tools ""             keine Built-in-Tools (kein Bash/Read/Edit/WebFetch), sonst könnte Claude vault.db
//                          direkt lesen
//   --strict-mcp-config    keine weiteren MCP-Server aus Nutzer- oder Projektkonfiguration
//   --setting-sources project, cwd = leeres Arbeitsverzeichnis: keine Hooks/Settings aus ~/.claude
//
// Eigenes Abo: jede Person meldet sich im Terminal mit ihrem eigenen Claude-Konto an (/login). Mit
// ARCA_CLAUDE_HOME bekommt jede angemeldete Dashboard-Person ein eigenes CLAUDE_CONFIG_DIR, Anmeldungen
// werden also nicht geteilt. Kein API-Key auf dem Server.
//
// Geschützte Eingabe: freies Tippen ist gesperrt, nur Steuertasten (Pfeile, Enter, Esc, Tab, Backspace,
// Ctrl-C, Ziffern für Menüs) gehen durch. Fragen kommen als {type:"prompt"} und werden HIER über den
// Arca-Service pseudonymisiert (/pseudonymize), bevor sie claude erreichen; der Browser kann das nicht
// umgehen. Direkteingabe (z. B. für /login) lässt sich freischalten und wieder sperren; beides steht mit der
// Person im Audit-Log von vault.db.
//
// Login (Server): mit ARCA_AUTH_API_URL muss der WebSocket-Request das Dashboard-Session-Cookie tragen;
// es wird bei der OpenAnonymizer-API geprüft (GET /v1/auth/me). Ohne gültige Sitzung: Code 4003.
// Die Umgebung von claude enthält keine ARCA_*/ANONYMIZER_*/ANTHROPIC_*-Variablen. mcp.json enthält nur den Pfad zu
// visible.db.
//
// Sperre: Eine Sitzung startet nur, wenn der Arca-Service "released" meldet. Wird die Freigabe
// widerrufen, wird die laufende Sitzung beendet.
//
// Nur lokale Verbindungen, Origin-Prüfung gegen Cross-Site-WebSocket-Hijacking.

import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import pty from "node-pty";

const here = dirname(fileURLToPath(import.meta.url));
const ARCA = resolve(here, "..");
const PORT = Number(process.env.ARCA_TERMINAL_PORT || 8101);
const HOST = process.env.ARCA_TERMINAL_HOST || "127.0.0.1";
const AUTH_API = process.env.ARCA_AUTH_API_URL || "";
const CLAUDE_HOME = process.env.ARCA_CLAUDE_HOME || "";
const SESSION_COOKIE = "anonymizer_session";
const SERVICE = process.env.ARCA_SERVICE_URL || "http://127.0.0.1:8100";
const ORIGINS = (process.env.ARCA_ALLOWED_ORIGINS || "http://localhost:3000,http://127.0.0.1:3000").split(",");
const DATA_DIR = resolve(process.env.ARCA_DATA_DIR || join(ARCA, "data"));
const VISIBLE = join(DATA_DIR, "visible.db");
const WORKSPACE = join(ARCA, "workspace");
const PYTHON = process.env.ARCA_PYTHON || "python3";
const CLAUDE = process.env.ARCA_CLAUDE_BIN || "claude";
const TOOLS = ["mcp__arca__list_tables", "mcp__arca__describe_table", "mcp__arca__query"];

export function mcpConfig() {
  return {
    mcpServers: {
      arca: { type: "stdio", command: PYTHON, args: ["-I", join(ARCA, "mcp", "server.py"), "--db", VISIBLE], env: {} },
    },
  };
}

export function claudeArgs(configPath) {
  return [
    "--strict-mcp-config", "--mcp-config", configPath,
    "--tools", "",
    "--allowedTools", TOOLS.join(","),
    "--setting-sources", "project",
  ];
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

// Einzelne Tastendrücke, die keinen Text transportieren.
const CONTROL_KEY = /^(?:\x1b(?:\[[0-9;]*[A-Za-z~]|O[A-Z])?|[\r\t\x7f\x03\x04\x08]|[0-9])$/;
export const isControlKey = data => CONTROL_KEY.test(data);

/** Steuernachricht an den Browser (nicht für das Terminal): Präfix \u0000arca: + JSON. */
export const CONTROL_PREFIX = "\u0000arca:";
const control = obj => CONTROL_PREFIX + JSON.stringify(obj);

/** Frage für claude: eine Zeile, pseudonymisiert durch den Arca-Service. */
export async function protectPrompt(text, service = SERVICE) {
  const res = await fetch(`${service}/pseudonymize`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`pseudonymize ${res.status}`);
  const out = await res.json();
  return { text: out.text.replace(/\s*\n\s*/g, " ").trim(), hints: out.hints ?? [] };
}

/** Ereignis ins Audit-Log; false, wenn es nicht geschrieben werden konnte. */
async function auditEvent(action, actor) {
  try {
    const res = await fetch(`${SERVICE}/audit`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, actor }),
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

export function claudeEnv(userId, env = process.env) {
  const out = cleanEnv(env);
  if (CLAUDE_HOME) {
    const dir = join(CLAUDE_HOME, createHash("sha256").update(String(userId)).digest("hex").slice(0, 24));
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    out.CLAUDE_CONFIG_DIR = dir;
    out.HOME = dir;
  }
  return out;
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
    const say = text => ws.send(`\r\n\x1b[33m${text}\x1b[0m\r\n`);
    const who = await user(req);
    if (!who) {
      say("Nicht angemeldet.");
      ws.close(4003, "login required");
      return;
    }
    if (!(await released())) {
      say("Erst freigeben. Claude startet erst, wenn Daten in A freigegeben sind.");
      ws.close(4001, "not released");
      return;
    }
    const config = prepareWorkspace();
    const term = pty.spawn(CLAUDE, claudeArgs(config), {
      name: "xterm-256color", cols: 100, rows: 28, cwd: WORKSPACE, env: claudeEnv(who.id),
    });
    term.onData(d => ws.readyState === ws.OPEN && ws.send(d));
    term.onExit(({ exitCode }) => {
      say(`claude beendet (Code ${exitCode}).`);
      ws.close(1000);
    });
    const watch = setInterval(async () => {
      if (!(await released())) {
        say("Freigabe widerrufen. Sitzung beendet.");
        term.kill();
      }
    }, 3000);
    let direct = false;
    let lastHint = 0;
    ws.send(control({ mode: "protected" }));
    ws.on("message", async raw => {
      let msg;
      try { msg = JSON.parse(String(raw)); } catch { return; }
      if (msg.type === "input" && typeof msg.data === "string") {
        if (direct || isControlKey(msg.data)) term.write(msg.data);
        else if (Date.now() - lastHint > 4000) {
          lastHint = Date.now();
          ws.send(control({ blocked: true }));
        }
      }
      if (msg.type === "prompt" && typeof msg.text === "string" && msg.text.trim() && msg.text.length <= 20000) {
        try {
          const safe = await protectPrompt(msg.text);
          term.write(safe.text);
          setTimeout(() => term.write("\r"), 50);
          ws.send(control({ sent: safe.text, hints: safe.hints }));
        } catch {
          ws.send(control({ error: "Frage konnte nicht pseudonymisiert werden und wurde nicht gesendet." }));
        }
      }
      if (msg.type === "unlock" && !direct) {
        // Nur freischalten, wenn das Freischalten protokolliert ist.
        if (!(await auditEvent("terminal_unlock", who.email))) {
          ws.send(control({ error: "Direkteingabe nicht freigeschaltet: Audit-Log nicht erreichbar." }));
          return;
        }
        direct = true;
        say("Direkteingabe freigeschaltet: Getipptes geht UNGEFILTERT an Claude. Nur für /login u. ä.");
        ws.send(control({ mode: "direct" }));
      }
      if (msg.type === "lock" && direct) {
        direct = false;
        await auditEvent("terminal_lock", who.email);
        ws.send(control({ mode: "protected" }));
      }
      if (msg.type === "resize" && msg.cols > 0 && msg.rows > 0) term.resize(Math.min(msg.cols, 400), Math.min(msg.rows, 200));
    });
    ws.on("close", () => {
      clearInterval(watch);
      try { term.kill(); } catch { /* schon beendet */ }
    });
  });

  console.log(`Arca-Terminal auf ws://${HOST}:${PORT} (Login: ${AUTH_API ? "Dashboard-Sitzung" : "aus"}) (Service ${SERVICE}, Origins ${ORIGINS.join(", ")})`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) start();

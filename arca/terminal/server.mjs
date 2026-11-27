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

/** Dashboard-Person zur Sitzung, oder null. Ohne ARCA_AUTH_API_URL (lokal): "local". */
async function user(req) {
  if (!AUTH_API) return "local";
  const token = sessionToken(req.headers.cookie);
  if (!token) return null;
  try {
    const res = await fetch(`${AUTH_API}/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return null;
    const me = await res.json();
    return me?.user?.id ?? null;
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
    const userId = await user(req);
    if (!userId) {
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
      name: "xterm-256color", cols: 100, rows: 28, cwd: WORKSPACE, env: claudeEnv(userId),
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
    ws.on("message", raw => {
      let msg;
      try { msg = JSON.parse(String(raw)); } catch { return; }
      if (msg.type === "input" && typeof msg.data === "string") term.write(msg.data);
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

// Arca-Terminal: WebSocket <-> node-pty, in dem die claude-CLI läuft.
//
// Claude bekommt genau einen Zugang zu Daten: den Arca-MCP-Server auf visible.db.
//   --tools ""             keine Built-in-Tools (kein Bash/Read/Edit/WebFetch), sonst könnte Claude vault.db
//                          direkt lesen
//   --strict-mcp-config    keine weiteren MCP-Server aus Nutzer- oder Projektkonfiguration
//   --setting-sources project, cwd = leeres Arbeitsverzeichnis: keine Hooks/Settings aus ~/.claude
//   --disable-slash-commands
// Die Umgebung von claude enthält keine ARCA_*/ANONYMIZER_*-Variablen. mcp.json enthält nur den Pfad zu
// visible.db.
//
// Sperre: Eine Sitzung startet nur, wenn der Arca-Service "released" meldet. Wird die Freigabe
// widerrufen, wird die laufende Sitzung beendet.
//
// Nur lokale Verbindungen, Origin-Prüfung gegen Cross-Site-WebSocket-Hijacking.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import pty from "node-pty";

const here = dirname(fileURLToPath(import.meta.url));
const ARCA = resolve(here, "..");
const PORT = Number(process.env.ARCA_TERMINAL_PORT || 8101);
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
    "--disable-slash-commands",
  ];
}

export function cleanEnv(env = process.env) {
  return Object.fromEntries(Object.entries(env).filter(([k]) => !/^(ARCA_|ANONYMIZER_)/.test(k)));
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
    host: "127.0.0.1", port: PORT,
    verifyClient: ({ origin }) => ORIGINS.includes(origin),
  });

  wss.on("connection", async ws => {
    const say = text => ws.send(`\r\n\x1b[33m${text}\x1b[0m\r\n`);
    if (!(await released())) {
      say("Erst freigeben. Claude startet erst, wenn Daten in A freigegeben sind.");
      ws.close(4001, "not released");
      return;
    }
    const config = prepareWorkspace();
    const term = pty.spawn(CLAUDE, claudeArgs(config), {
      name: "xterm-256color", cols: 100, rows: 28, cwd: WORKSPACE, env: cleanEnv(),
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

  console.log(`Arca-Terminal auf ws://127.0.0.1:${PORT} (Service ${SERVICE}, Origins ${ORIGINS.join(", ")})`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) start();

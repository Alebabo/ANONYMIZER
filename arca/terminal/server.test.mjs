// node --test: Claude startet ohne Built-in-Tools, nur mit dem Arca-MCP-Server, ohne Wissen über vault.db.
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import {
  LoginWatch, claudeArgs, claudeEnv, cleanEnv, isAuthCode, isControlKey, mcpConfig, protectPrompt, sessionToken,
  trustWorkspace,
} from "./server.mjs";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("keine Built-in-Tools, nur Arca-MCP", () => {
  const args = claudeArgs("/tmp/mcp.json");
  assert.equal(args[args.indexOf("--tools") + 1], "");
  assert.ok(args.includes("--strict-mcp-config"));
  assert.match(args[args.indexOf("--allowedTools") + 1], /^mcp__arca__/);
  assert.ok(!args.join(" ").includes("bypassPermissions"));
});

test("mcp.json kennt nur visible.db", () => {
  const cfg = JSON.stringify(mcpConfig());
  assert.ok(cfg.includes("visible.db"));
  assert.ok(!cfg.toLowerCase().includes("vault"));
  assert.deepEqual(Object.keys(mcpConfig().mcpServers), ["arca"]);
});

test("Umgebung ohne ARCA_/ANONYMIZER_", () => {
  const env = cleanEnv({ ARCA_SECRET: "x", ARCA_DATA_DIR: "/d", ANONYMIZER_VAULT_KEY: "k", PATH: "/bin" });
  assert.deepEqual(env, { PATH: "/bin" });
});

test("Session-Cookie wird gelesen", () => {
  assert.equal(sessionToken("a=1; anonymizer_session=abc%3D; b=2"), "abc=");
  assert.equal(sessionToken("a=1"), null);
  assert.equal(sessionToken(undefined), null);
});

test("kein API-Key, eigenes Abo per /login möglich", () => {
  const args = claudeArgs("/tmp/mcp.json").join(" ");
  assert.ok(!args.includes("--disable-slash-commands"));  // /login muss gehen
  assert.deepEqual(cleanEnv({ ANTHROPIC_API_KEY: "x", ANTHROPIC_AUTH_TOKEN: "y", PATH: "/bin" }), { PATH: "/bin" });
});

test("geschützte Eingabe: nur Steuertasten", () => {
  for (const k of ["\r", "\x1b", "\x1b[A", "\x1b[B", "\x1b[3~", "\t", "\x7f", "\x03", "1", "2"]) assert.ok(isControlKey(k), JSON.stringify(k));
  for (const k of ["a", "M", "Max Mustermann", "\x1b[200~Keller\x1b[201~", "12", " ", "/login"]) assert.ok(!isControlKey(k), JSON.stringify(k));
});

test("Fragen werden über den Service pseudonymisiert", async () => {
  let body = null;
  const srv = http.createServer((req, res) => {
    let raw = "";
    req.on("data", c => { raw += c; });
    req.on("end", () => {
      body = JSON.parse(raw);
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ text: "Was ist mit\nPERSON_1a2b3c4d?", hints: ["Lüneburg"] }));
    });
  });
  await new Promise(r => srv.listen(0, "127.0.0.1", r));
  const out = await protectPrompt("Was ist mit Max Mustermann?", `http://127.0.0.1:${srv.address().port}`);
  srv.close();
  assert.equal(body.text, "Was ist mit Max Mustermann?");
  assert.deepEqual(out, { text: "Was ist mit PERSON_1a2b3c4d?", hints: ["Lüneburg"] });
});

test("Login-Code: nur Token-förmig", () => {
  assert.ok(isAuthCode("aBcD1234efGH5678ijKL9012mnOP#state_XYZ-123"));
  assert.ok(isAuthCode("  aBcD1234efGH5678ijKL9012mnOP  "));
  for (const t of ["Max Mustermann", "Wie stehen die Chancen von Frau Keller?", "kurz", "", "abc def ghi jkl mno pqr stu", null]) {
    assert.ok(!isAuthCode(t), JSON.stringify(t));
  }
});

test("Login-Schritt und URL werden erkannt", () => {
  const w = new LoginWatch();
  assert.equal(w.feed("\x1b[1mWelcome to Claude Code\x1b[0m\r\n"), null);
  const url = "https://claude.ai/oauth/authorize?code=true&client_id=abc&state=xyz";
  const change = w.feed(`Browser didn't open? Use the url below\r\n\x1b[4m${url}\x1b[24m\r\n Paste code here if prompted \r\n`);
  assert.deepEqual(change, { login: true, url });
  assert.equal(w.feed("Paste code here"), null);  // nur einmal melden
  assert.deepEqual(w.reset(), { login: false });
  assert.equal(w.feed("weiter"), null);
});

test("Login-URL aus OSC-8-Hyperlink (vollständig, auch bei Umbruch)", () => {
  const w = new LoginWatch();
  const url = "https://claude.ai/oauth/authorize?code=true&client_id=" + "a".repeat(150);
  const change = w.feed(`\x1b]8;;${url}\x07${url.slice(0, 90)}\r\n${url.slice(90)}\x1b]8;;\x07\r\nPaste code here`);
  assert.equal(change.url, url);
});

test("Arbeitsverzeichnis vorab vertraut, bestehende Konfiguration bleibt erhalten", () => {
  const dir = mkdtempSync(join(tmpdir(), "arca-claude-"));
  writeFileSync(join(dir, ".claude.json"), JSON.stringify({ oauthAccount: { x: 1 }, projects: { "/a": { foo: 1 } } }));
  trustWorkspace(dir, "/ws");
  const cfg = JSON.parse(readFileSync(join(dir, ".claude.json"), "utf8"));
  assert.deepEqual(cfg.oauthAccount, { x: 1 });
  assert.deepEqual(cfg.projects["/a"], { foo: 1 });
  assert.equal(cfg.projects["/ws"].hasTrustDialogAccepted, true);
});

test("eigenes Konfigurationsverzeichnis je Person", () => {
  const home = mkdtempSync(join(tmpdir(), "arca-home-"));
  const a = claudeEnv("usr_a", { PATH: "/bin", ANTHROPIC_API_KEY: "k" }, home);
  const b = claudeEnv("usr_b", { PATH: "/bin" }, home);
  assert.notEqual(a.CLAUDE_CONFIG_DIR, b.CLAUDE_CONFIG_DIR);
  assert.ok(a.CLAUDE_CONFIG_DIR.startsWith(home) && a.HOME === a.CLAUDE_CONFIG_DIR);
  assert.equal(a.ANTHROPIC_API_KEY, undefined);
});

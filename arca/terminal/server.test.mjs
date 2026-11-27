// node --test: Claude startet ohne Built-in-Tools, nur mit dem Arca-MCP-Server, ohne Wissen über vault.db.
import test from "node:test";
import assert from "node:assert/strict";
import { claudeArgs, cleanEnv, mcpConfig, sessionToken } from "./server.mjs";

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

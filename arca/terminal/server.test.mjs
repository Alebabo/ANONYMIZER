// node --test: Claude startet ohne Built-in-Tools, nur mit dem Arca-MCP-Server, ohne Wissen über vault.db.
import test from "node:test";
import assert from "node:assert/strict";
import { claudeArgs, cleanEnv, mcpConfig } from "./server.mjs";

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

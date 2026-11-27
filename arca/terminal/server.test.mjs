// node --test: Claude startet ohne Built-in-Tools, nur mit dem Arca-MCP-Server, ohne Wissen über vault.db.
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { claudeArgs, cleanEnv, isControlKey, mcpConfig, protectPrompt, sessionToken } from "./server.mjs";

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

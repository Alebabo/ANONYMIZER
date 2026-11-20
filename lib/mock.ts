// Illustrative example data in the shape of the OpenAnonymizer API. No real content.
import type {
  ApiKey, AuditEntry, Dataset, Info, PlaygroundResult, Me, PolicySummary, SourcesInfo, Trace, User,
} from "@/lib/anonymizer-api";

export const exampleInfo: Info = {
  version: "0.1.0", ner: "available", vault: true, admin_endpoints: true, default_policy: "banking-default",
  trace_content: false, trace_retention_days: 30,
};

const base = Date.now() / 1000;
export const exampleTraces: Trace[] = [
  {
    id: "req_5d1a7c3e90b2", created_at: base - 60, route: "/mcp/proxy", client: "mcp", actor: "claude-code", outcome: "local_only", allowed: false,
    risk: "critical", needs_review: false, policy: "support-default@v1", policy_hash: "sha256:4be1…",
    destination: "external", provider: "mcp", model: "demo", language: "de", latency_ms: 48.2, status: 200,
    error: null, entity_counts: { person: 7, email: 3, phone: 3, iban: 3, health_data: 1, address: 1 },
    risk_counts: { critical: 4, sensitive: 14 },
    actions: { "person:pseudonymize": 7, "email:pseudonymize": 3, "phone:pseudonymize": 3, "iban:redact": 3,
      "health_data:local_only": 1, "address:pseudonymize": 1 }, transformations: 17, signals: [], warnings: [],
    upstream: "demo", tool: "get_customers", mode: "enforce",
    fields: { "$.vorname": { person: 3 }, "$.nachname": { person: 3 }, "$.email": { email: 3 },
      "$.telefon": { phone: 3 }, "$.iban": { iban: 3 }, "$.notiz": { person: 1, health_data: 1, address: 1 } },
    steps: [
      { name: "Tool call", detail: "demo · get_customers", status: "ok" },
      { name: "Upstream response", detail: "3 content block(s) in 12 ms", status: "ok" },
      { name: "Privacy detection", detail: "20 values analysed · 19 entities in 6 field(s) · 3 by field name", status: "ok" },
      { name: "Policy evaluation", detail: "support-default@v1 → local_only · 1 value(s) withheld", status: "blocked" },
      { name: "Anonymization", detail: "17 transformations · 0 non-text block(s) withheld", status: "ok" },
    ],
  },
  {
    id: "req_9e4f02b7c6d1", created_at: base - 90, route: "/mcp/proxy", client: "mcp", actor: "claude-code", outcome: "allow", allowed: true,
    risk: "critical", needs_review: false, policy: "support-default@v1", policy_hash: "sha256:4be1…",
    destination: "external", provider: "mcp", model: "demo", language: "de", latency_ms: 21.6, status: 200,
    error: null, entity_counts: { person: 3, phone: 1, iban: 1 }, risk_counts: { critical: 1, sensitive: 4 },
    actions: { "person:pseudonymize": 3, "phone:pseudonymize": 1, "iban:redact": 1 }, transformations: 5,
    signals: [], warnings: [], upstream: "demo", tool: "get_tickets", mode: "observe",
    fields: { "$.text": { person: 3, phone: 1, iban: 1 } },
    steps: [
      { name: "Tool call", detail: "demo · get_tickets", status: "ok" },
      { name: "Privacy detection", detail: "6 values analysed · 5 entities in 1 field(s) · 1 known value(s) in free text", status: "ok" },
      { name: "Observe mode", detail: "original result returned · 2 value(s) would have been changed", status: "warning" },
    ],
  },
  {
    id: "req_8f29a1c0d2e4", created_at: base - 120, route: "/v1/chat/completions", client: "api", actor: "support-bot", outcome: "allow", allowed: true,
    risk: "critical", needs_review: false, policy: "banking-default@v1", policy_hash: "sha256:c9218375…",
    destination: "external", provider: "openai", model: "gpt-4o", language: "de", latency_ms: 182.3, status: 200,
    error: null, entity_counts: { person: 2, iban: 1, case_number: 1 }, risk_counts: { critical: 2, sensitive: 2 },
    actions: { "person:pseudonymize": 2, "iban:redact": 1, "case_number:pseudonymize": 1 }, transformations: 4,
    signals: ["client_relationship"], warnings: [],
    steps: [
      { name: "Request received", detail: "POST /v1/chat/completions · 2 text part(s)", status: "ok" },
      { name: "Privacy detection", detail: "4 entities detected", status: "ok" },
      { name: "Classification", detail: "risk critical", status: "ok" },
      { name: "Policy evaluation", detail: "banking-default@v1 → allow", status: "ok" },
      { name: "Anonymization", detail: "4 transformations applied", status: "ok" },
      { name: "Provider request", detail: "openai · gpt-4o · HTTP 200", status: "ok" },
      { name: "Response restore", detail: "2 placeholder(s) restored, 0 unknown", status: "ok" },
    ],
  },
  {
    id: "req_41c07e9b11aa", created_at: base - 300, route: "/v1/chat/completions", client: "api", actor: "support-bot", outcome: "local_only", allowed: false,
    risk: "critical", needs_review: false, policy: "banking-default@v1", policy_hash: "sha256:c9218375…",
    destination: "external", provider: "openai", model: "gpt-4o", language: "de", latency_ms: 64.1, status: 403,
    error: null, entity_counts: { person: 1, health_data: 1 }, risk_counts: { critical: 2 },
    actions: { "person:pseudonymize": 1, "health_data:local_only": 1 }, transformations: 0, signals: [], warnings: [],
    steps: [
      { name: "Request received", detail: "POST /v1/chat/completions · 1 text part(s)", status: "ok" },
      { name: "Privacy detection", detail: "2 entities detected", status: "ok" },
      { name: "Classification", detail: "risk critical", status: "ok" },
      { name: "Policy evaluation", detail: "banking-default@v1 → local_only", status: "blocked" },
    ],
  },
  {
    id: "req_b92d10f7a6c3", created_at: base - 900, route: "/v1/documents/protect", client: "dashboard", actor: "admin@kanzlei.example", outcome: "review", allowed: false,
    risk: "sensitive", needs_review: true, policy: "banking-default@v1", policy_hash: "sha256:c9218375…",
    destination: "external", provider: null, model: null, language: "de", latency_ms: 95.0, status: 200, error: null,
    entity_counts: { person: 4, address: 1 }, risk_counts: { sensitive: 5 }, actions: { "person:pseudonymize": 4, "address:pseudonymize": 1 },
    transformations: 0, signals: ["litigation"], warnings: ["document contains comments (not anonymized)"],
    steps: [
      { name: "Request received", detail: "/v1/documents/protect", status: "ok" },
      { name: "Document parsed", detail: "docx · 1 warning(s)", status: "warning" },
      { name: "Privacy detection", detail: "5 entities detected", status: "warning" },
      { name: "Classification", detail: "0 critical · 5 sensitive · risk sensitive", status: "warning" },
      { name: "Policy evaluation", detail: "banking-default@v1 → review", status: "blocked" },
    ],
  },
];

export const examplePolicies: PolicySummary[] = [
  { name: "banking-default", version: 1, hash: "sha256:c9218375cb8d…", scope: { tenant: null, team: null } },
  { name: "firm-a", version: 3, hash: "sha256:7a0e51f2c4b9…", scope: { tenant: "firm-a", team: null } },
];

export const examplePolicyYaml = `name: banking-default
version: 1
rules:
  - id: customers
    entity: [person, organization, location]
    action: pseudonymize
  - id: accounts
    entity: [iban, customer_number, account_number]
    action: pseudonymize
  - id: identifiers
    entity: [credit_card, tax_id, social_security_number]
    action: redact
  - id: special_categories_external
    category: special_category
    destinations: [external]
    action: local_only
    priority: 10
document_rules:
  - id: financial_distress_review
    min_risk: critical
    signals: [financial_distress]
    destinations: [external]
    action: review
default_action: redact`;

const day = 86400;

export const exampleMembers: User[] = [
  { id: "usr_3f1a9c0b7d2e", org_id: "default", email: "admin@kanzlei.example", name: "Dr. Example Admin", role: "admin",
    created_at: base - 30 * day, last_login_at: base - 600, disabled: false },
  { id: "usr_8b2e4d6f1a0c", org_id: "default", email: "it@kanzlei.example", name: "IT Team", role: "member",
    created_at: base - 12 * day, last_login_at: base - 2 * day, disabled: false },
];

export const exampleMe: Me = {
  kind: "session", role: "admin", user: exampleMembers[0],
  organization: { id: "default", name: "Example Firm", created_at: base - 30 * day, trace_retention_days: null,
                  effective_trace_retention_days: 30 },
};

export const exampleApiKeys: ApiKey[] = [
  { id: "key_a1b2c3d4e5f6", org_id: "default", name: "Contract review backend", prefix: "anonymizer_Xr8vQ2p", role: "user",
    created_by: "usr_3f1a9c0b7d2e", created_at: base - 20 * day, last_used_at: base - 120, revoked_at: null },
  { id: "key_0f9e8d7c6b5a", org_id: "default", name: "Policy deployment (CI)", prefix: "anonymizer_Lm3Tz9a", role: "admin",
    created_by: "usr_3f1a9c0b7d2e", created_at: base - 9 * day, last_used_at: base - 3 * day, revoked_at: null },
  { id: "key_5a4b3c2d1e0f", org_id: "default", name: "Old prototype", prefix: "anonymizer_P0qWe7r", role: "user",
    created_by: "usr_3f1a9c0b7d2e", created_at: base - 28 * day, last_used_at: base - 15 * day, revoked_at: base - 14 * day },
];

const admin = { actor_type: "user" as const, actor_id: "usr_3f1a9c0b7d2e", actor_label: "admin@kanzlei.example" };
const entry = (i: number, ago: number, e: Partial<AuditEntry>): AuditEntry => ({
  seq: i, id: `aud_example${String(i).padStart(5, "0")}`, created_at: base - ago, org_id: "default",
  ...admin, resource_type: "", resource_id: "", action: "", before: null, after: null,
  prev_hash: "", hash: `example${i}`, ...e,
});
export const exampleAudit: AuditEntry[] = [
  entry(9, 300, { actor_type: "api_key", actor_id: "key_0f9e8d7c6b5a", actor_label: "Policy deployment (CI) (anonymizer_Lm3Tz9a…)",
    resource_type: "vault", resource_id: "matter-2026-114", action: "restore", after: { restored: 3, unresolved: 0 } }),
  entry(8, 600, { resource_type: "session", resource_id: "usr_3f1a9c0b7d2e", action: "login" }),
  entry(7, 900, { actor_type: "anonymous", actor_id: null, actor_label: "admin@kanzlei.example",
    resource_type: "session", resource_id: "usr_3f1a9c0b7d2e", action: "login_failed" }),
  entry(6, 2 * day, { actor_type: "api_key", actor_id: "key_0f9e8d7c6b5a", actor_label: "Policy deployment (CI) (anonymizer_Lm3Tz9a…)",
    resource_type: "policy", resource_id: "firm-a", action: "update",
    before: { name: "firm-a", version: 2, hash: "sha256:51c0…", scope: { tenant: "firm-a", team: null } },
    after: { name: "firm-a", version: 3, hash: "sha256:7a0e…", scope: { tenant: "firm-a", team: null } } }),
  entry(5, 9 * day, { resource_type: "api_key", resource_id: "key_0f9e8d7c6b5a", action: "create",
    after: { id: "key_0f9e8d7c6b5a", name: "Policy deployment (CI)", prefix: "anonymizer_Lm3Tz9a", role: "admin", revoked_at: null } }),
  entry(4, 12 * day, { resource_type: "member", resource_id: "usr_8b2e4d6f1a0c", action: "create",
    after: { id: "usr_8b2e4d6f1a0c", email: "it@kanzlei.example", name: "IT Team", role: "member", disabled: false } }),
  entry(3, 14 * day, { resource_type: "api_key", resource_id: "key_5a4b3c2d1e0f", action: "revoke",
    before: { id: "key_5a4b3c2d1e0f", name: "Old prototype", role: "user", revoked_at: null },
    after: { id: "key_5a4b3c2d1e0f", name: "Old prototype", role: "user", revoked_at: base - 14 * day } }),
  entry(2, 29 * day, { resource_type: "organization", resource_id: "default", action: "update",
    before: { id: "default", name: "Default", trace_retention_days: null },
    after: { id: "default", name: "Example Firm", trace_retention_days: null } }),
  entry(1, 30 * day, { actor_type: "system", actor_id: null, actor_label: "system (cli)", resource_type: "member",
    resource_id: "usr_3f1a9c0b7d2e", action: "create",
    after: { id: "usr_3f1a9c0b7d2e", email: "admin@kanzlei.example", role: "admin", disabled: false } }),
];

// -- conversations & prompts (synthetic) -------------------------------------------

export const exampleSources: SourcesInfo = {
  conversations: { kind: "langfuse", location: "https://langfuse.internal.example", daily_limit: 200, min_group: 10,
                   stable_placeholders: true },
  conversation_policy: "support-default",
  prompts: { backend: "langfuse", location: "https://langfuse.internal.example" },
  mcp_http: true,
};

export const exampleDatasets: Dataset[] = [
  { id: "ds_demo000001", name: "kunden-beispiel.csv", columns: ["kunden_id", "vorname", "nachname", "email", "iban", "anliegen"],
    rows: 3, created_at: Date.now() / 1000 - 600, created_by: "admin@example.org" },
];

const demoRows = [
  { kunden_id: "K-1001", vorname: "Max", nachname: "Mustermann", email: "max@example.org", iban: "DE89370400440532013000",
    anliegen: "Herr Mustermann möchte sein Limit erhöhen." },
  { kunden_id: "K-1002", vorname: "Erika", nachname: "Musterfrau", email: "erika@example.org", iban: "DE02120300000000202051",
    anliegen: "Karte gesperrt, bitte Rückruf an 0151 23456789." },
  { kunden_id: "K-1003", vorname: "Jan", nachname: "Beispiel", email: "jan@example.org", iban: "DE02500105170137075030",
    anliegen: "Frage zur Überweisung vom 12.11." },
];
const demoSent = [
  { kunden_id: "K-1001", vorname: "PERSON_001", nachname: "PERSON_002", email: "EMAIL_001", iban: "[IBAN]",
    anliegen: "Herr PERSON_002 möchte sein Limit erhöhen." },
  { kunden_id: "K-1002", vorname: "PERSON_003", nachname: "PERSON_004", email: "EMAIL_002", iban: "[IBAN]",
    anliegen: "Karte gesperrt, bitte Rückruf an PHONE_001." },
  { kunden_id: "K-1003", vorname: "PERSON_005", nachname: "PERSON_006", email: "EMAIL_003", iban: "[IBAN]",
    anliegen: "Frage zur Überweisung vom 12.11." },
];

export function examplePlayground(query?: string): PlaygroundResult {
  const q = (query ?? "").toLowerCase();
  const idx = demoRows.map((r, i) => (Object.values(r).some(v => v.toLowerCase().includes(q)) ? i : -1)).filter(i => i >= 0);
  const rows = idx.map(i => demoSent[i]!);
  return {
    dataset: { id: "ds_demo000001", name: "kunden-beispiel.csv", rows: 3 }, columns: exampleDatasets[0]!.columns,
    matched: idx.length, offset: 0, limit: 20, rows, trace_id: exampleTraces[0]!.id,
    original: idx.map(i => demoRows[i]!), sent: JSON.stringify(rows, null, 2), withheld: 0,
    entities: { person: idx.length * 2 + (idx.includes(0) ? 1 : 0), email: idx.length, iban: idx.length, phone: idx.includes(1) ? 1 : 0 },
    replacements: idx.flatMap(i => [
      { type: "person", original: demoRows[i]!.vorname, replacement: demoSent[i]!.vorname, field: "$[].vorname", method: "pseudonymize" },
      { type: "person", original: demoRows[i]!.nachname, replacement: demoSent[i]!.nachname, field: "$[].nachname", method: "pseudonymize" },
      { type: "email", original: demoRows[i]!.email, replacement: demoSent[i]!.email, field: "$[].email", method: "pseudonymize" },
      { type: "iban", original: demoRows[i]!.iban, replacement: "[IBAN]", field: "$[].iban", method: "redact" },
    ]),
  };
}

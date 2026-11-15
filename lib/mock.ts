// Illustrative example data in the shape of the Cato API. No real content.
import type { Metrics, PolicySummary, Trace } from "@/lib/cato-api";

const now = Math.floor(Date.now() / 1000 / 3600) * 3600;

export const exampleMetrics: Metrics = {
  window_hours: 24,
  requests: 24891,
  requests_with_detections: 3421,
  detection_rate: 0.137,
  detections: 9120,
  anonymized_entities: 7505,
  anonymization_rate: 0.823,
  not_allowed: 104,
  block_rate: 0.0042,
  by_outcome: { allow: 24787, review: 61, local_only: 38, block: 5 },
  by_risk: { low: 18012, sensitive: 4410, critical: 2469 },
  by_route: { "/v1/chat/completions": 19870, "/v1/protect": 4120, "/v1/documents/protect": 901 },
  by_provider: { openai: 17210, azure: 2420, local: 240 },
  by_policy: { "legal-default@v1": 21890, "firm-a@v3": 3001 },
  entity_distribution: { person: 3910, organization: 1820, case_number: 980, email: 760, iban: 412, health_data: 96, date_of_birth: 88 },
  actions: { pseudonymize: 6610, redact: 812, generalize: 83, allow: 1511, local_only: 38, review: 61, block: 5 },
  latency_ms: { avg: 182.4, p95: 412.0 },
  errors: 12,
  timeseries: Array.from({ length: 24 }, (_, i) => ({
    t: now - (23 - i) * 3600,
    requests: Math.round(700 + 450 * Math.sin((i / 24) * Math.PI) + (i % 5) * 37),
  })),
};

const base = Date.now() / 1000;
export const exampleTraces: Trace[] = [
  {
    id: "req_8f29a1c0d2e4", created_at: base - 120, route: "/v1/chat/completions", outcome: "allow", allowed: true,
    risk: "critical", needs_review: false, policy: "legal-default@v1", policy_hash: "sha256:c9218375…",
    destination: "external", provider: "openai", model: "gpt-4o", language: "de", latency_ms: 182.3, status: 200,
    error: null, entity_counts: { person: 2, iban: 1, case_number: 1 }, risk_counts: { critical: 2, sensitive: 2 },
    actions: { "person:pseudonymize": 2, "iban:redact": 1, "case_number:pseudonymize": 1 }, transformations: 4,
    signals: ["client_relationship"], warnings: [],
    steps: [
      { name: "Request received", detail: "POST /v1/chat/completions · 2 text part(s)", status: "ok" },
      { name: "Privacy detection", detail: "4 entities detected", status: "ok" },
      { name: "Classification", detail: "risk critical", status: "ok" },
      { name: "Policy evaluation", detail: "legal-default@v1 → allow", status: "ok" },
      { name: "Anonymization", detail: "4 transformations applied", status: "ok" },
      { name: "Provider request", detail: "openai · gpt-4o · HTTP 200", status: "ok" },
      { name: "Response restore", detail: "2 placeholder(s) restored, 0 unknown", status: "ok" },
    ],
  },
  {
    id: "req_41c07e9b11aa", created_at: base - 300, route: "/v1/chat/completions", outcome: "local_only", allowed: false,
    risk: "critical", needs_review: false, policy: "legal-default@v1", policy_hash: "sha256:c9218375…",
    destination: "external", provider: "openai", model: "gpt-4o", language: "de", latency_ms: 64.1, status: 403,
    error: null, entity_counts: { person: 1, health_data: 1 }, risk_counts: { critical: 2 },
    actions: { "person:pseudonymize": 1, "health_data:local_only": 1 }, transformations: 0, signals: [], warnings: [],
    steps: [
      { name: "Request received", detail: "POST /v1/chat/completions · 1 text part(s)", status: "ok" },
      { name: "Privacy detection", detail: "2 entities detected", status: "ok" },
      { name: "Classification", detail: "risk critical", status: "ok" },
      { name: "Policy evaluation", detail: "legal-default@v1 → local_only", status: "blocked" },
    ],
  },
  {
    id: "req_b92d10f7a6c3", created_at: base - 900, route: "/v1/documents/protect", outcome: "review", allowed: false,
    risk: "sensitive", needs_review: true, policy: "legal-default@v1", policy_hash: "sha256:c9218375…",
    destination: "external", provider: null, model: null, language: "de", latency_ms: 95.0, status: 200, error: null,
    entity_counts: { person: 4, address: 1 }, risk_counts: { sensitive: 5 }, actions: { "person:pseudonymize": 4, "address:pseudonymize": 1 },
    transformations: 0, signals: ["litigation"], warnings: ["document contains comments (not anonymized)"],
    steps: [
      { name: "Request received", detail: "/v1/documents/protect", status: "ok" },
      { name: "Document parsed", detail: "docx · 1 warning(s)", status: "warning" },
      { name: "Privacy detection", detail: "5 entities detected", status: "warning" },
      { name: "Classification", detail: "0 critical · 5 sensitive · risk sensitive", status: "warning" },
      { name: "Policy evaluation", detail: "legal-default@v1 → review", status: "blocked" },
    ],
  },
];

export const examplePolicies: PolicySummary[] = [
  { name: "legal-default", version: 1, hash: "sha256:c9218375cb8d…", scope: { tenant: null, team: null } },
  { name: "firm-a", version: 3, hash: "sha256:7a0e51f2c4b9…", scope: { tenant: "firm-a", team: null } },
];

export const examplePolicyYaml = `name: legal-default
version: 1
rules:
  - id: parties
    entity: [person, organization, location]
    action: pseudonymize
  - id: identifiers
    entity: [iban, credit_card, tax_id, social_security_number]
    action: redact
  - id: special_categories_external
    category: special_category
    destinations: [external]
    action: local_only
    priority: 10
document_rules:
  - id: criminal_privileged_review
    min_risk: critical
    signals: [criminal_proceeding]
    destinations: [external]
    action: review
default_action: redact`;

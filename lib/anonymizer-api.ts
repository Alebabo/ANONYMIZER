import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  exampleApiKeys, exampleAudit, exampleConversation, exampleConversations, exampleConversationStats, exampleGateway,
  exampleInfo, exampleDatasets, exampleMe, exampleMembers, examplePlayground, exampleMetrics, examplePolicies, examplePromptHistory, examplePrompts, examplePromptVersion,
  exampleProxy, exampleSources, exampleTraces,
} from "@/lib/mock";

/**
 * Server-side access to the OpenAnonymizer API. Tokens never reach browser JavaScript.
 *
 * Modes:
 *  - demo: ANONYMIZER_API_URL is not set. Pages show clearly labelled example data, no login.
 *  - live: ANONYMIZER_API_URL is set. Every page requires a login (middleware.ts); calls use the
 *    user's session token (httpOnly cookie), so the API enforces roles and organization scope.
 */

export const SESSION_COOKIE = "anonymizer_session";

export type Trace = {
  id: string; created_at: number; route: string; outcome: string | null; allowed: boolean | null;
  risk: string | null; needs_review: boolean; policy: string | null; policy_hash: string | null;
  destination: string | null; provider: string | null; model: string | null; language: string | null;
  latency_ms: number | null; status: number; error: string | null; entity_counts: Record<string, number>;
  risk_counts: Record<string, number>; actions: Record<string, number>; transformations: number;
  signals: string[]; warnings: string[]; steps: { name: string; detail: string; status: string }[];
  /** MCP proxy traces only: upstream system, tool, mode and entity types per JSON field path. */
  upstream?: string | null; tool?: string | null; mode?: string | null;
  fields?: Record<string, Record<string, number>>;
  /** What was read, e.g. a conversation id. */
  resource?: string | null;
  /** Only with ANONYMIZER_TRACE_CONTENT=1 and for admins: protected text and original values. */
  content?: TraceContent[];
};

export type TraceContent = {
  label: string | null; input?: string | null; output: string | null; withheld: boolean;
  replacements: { type: string; original: string; replacement: string | null; method: string | null }[];
};

export type ProxyUpstream = {
  name: string; transport: "stdio" | "http"; mode: "enforce" | "observe"; policy: string; connected: boolean;
  error: string | null; tools_upstream: number; tools_exposed: number;
};
export type ProxyStatus = { path: string; destination: string; upstreams: ProxyUpstream[]; tools: string[] };

export type SeriesPoint = {
  t: number; requests: number; clean?: number; anonymized?: number; not_allowed?: number; errors?: number; entities?: number;
};
export type Operation = {
  name: string; calls: number; entities: number; not_allowed: number; errors: number; observe: number; p95_ms: number | null;
};
export type Metrics = {
  window_hours: number; bucket_seconds?: number; requests: number; requests_with_detections: number; detection_rate: number;
  detections: number; entities_per_request?: number; anonymized_entities: number; anonymization_rate: number;
  not_allowed: number; block_rate: number; needs_review?: number; with_warnings?: number; observe_mode?: number;
  resources_read?: number; by_outcome: Record<string, number>; by_risk: Record<string, number>;
  by_route: Record<string, number>; by_provider: Record<string, number>; by_policy: Record<string, number>;
  by_operation?: Operation[]; top_fields?: Record<string, number>; warnings?: Record<string, number>;
  entity_distribution: Record<string, number>; actions: Record<string, number>;
  latency_ms: { avg: number | null; p50?: number | null; p95: number | null; p99?: number | null }; errors: number;
  previous?: { requests: number; detections: number; not_allowed: number; errors: number };
  last_trace_at?: number | null;
  timeseries: SeriesPoint[];
};

export type Info = {
  version: string; ner: "available" | "unavailable" | "disabled"; vault: boolean; admin_endpoints: boolean;
  default_policy: string; trace_content?: boolean; trace_retention_days?: number;
};

export type PolicySummary = { name: string; version: number; hash: string; scope: Record<string, unknown> };

export type User = {
  id: string; org_id: string; email: string; name: string; role: "admin" | "member";
  created_at: number; last_login_at: number | null; disabled: boolean;
};
export type Organization = {
  id: string; name: string; created_at: number; trace_retention_days: number | null;
  effective_trace_retention_days: number;
};
export type Me = { kind: string; role: string; user: User | null; organization: Organization };

export type ApiKey = {
  id: string; org_id: string; name: string; prefix: string; role: "user" | "admin"; created_by: string | null;
  created_at: number; last_used_at: number | null; revoked_at: number | null;
};

export type AuditEntry = {
  seq: number; id: string; created_at: number; org_id: string; actor_type: "user" | "api_key" | "system" | "anonymous";
  actor_id: string | null; actor_label: string | null; resource_type: string; resource_id: string; action: string;
  before: unknown; after: unknown; prev_hash: string; hash: string;
};
export type AuditPage = { data: AuditEntry[]; next_before: number | null; actions: string[]; resource_types: string[] };
export type AuditVerify = { ok: boolean; entries: number; broken_at: string | null; head?: string };

type Upstream = { host: string; provider: string; model: string | null; authenticated: boolean } | null;
export type GatewayStatus = {
  external: Upstream; local: Upstream; restore_responses: boolean; timeout_s: number; streaming: boolean;
  endpoint: string; default_policy: string;
};

export type Source = { live: boolean; reason?: string };

export type SourcesInfo = {
  conversations: { kind: string; location: string; daily_limit: number; min_group: number; stable_placeholders: boolean } | null;
  conversation_policy: string | null;
  prompts: { backend: string; location?: string } | null;
  mcp_http: boolean;
};
export type ConversationHead = {
  id: string; day: string; message_count: number | null; language: string | null; channel: string | null;
  tags: string[]; prompt: string | null; prompt_version: number | null;
};
export type ConversationPage = { data: ConversationHead[]; next_cursor: string | null };
export type ConversationMessage = {
  role: string; content: string | null; minute?: number; withheld?: boolean; outcome?: string; reason?: string;
};
export type Conversation = ConversationHead & {
  outcome: string; risk: string; withheld: number; truncated: boolean; messages: ConversationMessage[];
  trace_id: string; stable_placeholders: boolean; quota: { used: number; limit: number; remaining: number };
};
export type ConversationStats = {
  group_by: string; min_group: number; total: number | null; suppressed_groups: number; scanned: number; truncated: boolean;
  groups: { key: string; conversations: number; messages: number }[];
};
export type Quota = { used: number; limit: number; remaining: number };
export type PromptListItem = { name: string; latest_version: number; versions: number; labels: Record<string, number>; updated_at: number | null };
export type PromptMessage = { role: string; content: string | null };
export type PromptVersion = {
  name: string; version: number; type: "text" | "chat"; prompt: string | PromptMessage[] | null; config: Record<string, unknown>;
  labels: string[]; note: string | null; created_by: string | null; created_at: number | null; hash: string;
  protected: boolean; warnings?: string[]; notice?: string;
};
export type PromptHistoryItem = {
  version: number; labels: string[]; note: string | null; created_by: string | null; created_at: number | null; hash: string; type: string;
};
export type PromptDiff = { name: string; from: number; to: number; diff: string; config_changed: boolean; protected: boolean };

export type Dataset = { id: string; name: string; columns: string[]; rows: number; created_at: number; created_by: string | null };
export type PlaygroundResult = {
  dataset: { id: string; name: string; rows: number }; columns: string[]; matched: number; offset: number; limit: number;
  rows: Record<string, unknown>[] | string; trace_id: string;
  /** Dashboard sessions only. */
  original?: Record<string, string>[]; sent?: string; entities?: Record<string, number>; withheld?: number;
  replacements?: { type: string; original: string; replacement: string | null; field: string | null; method: string | null }[];
};

export const isDemo = () => !process.env.ANONYMIZER_API_URL;
const base = () => process.env.ANONYMIZER_API_URL!.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function token(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Authenticated call with the user's session. 401 sends the user to the login page. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const t = await token();
  if (!t) redirect("/login");
  const res = await fetch(`${base()}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json", ...init.headers },
    cache: "no-store",
  });
  if (res.status === 401) redirect("/login?expired=1");
  if (!res.ok) {
    let detail = `OpenAnonymizer API ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch { /* keep generic message */ }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : res.json()) as Promise<T>;
}

/** Unauthenticated login call (used by the login server action only). */
export async function apiLogin(email: string, password: string) {
  const res = await fetch(`${base()}/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  if (!res.ok) {
    const msg = res.status === 429 ? "Too many failed attempts. Try again in 15 minutes."
      : res.status === 401 || res.status === 422 ? "Invalid e-mail or password." : `Login failed (API ${res.status}).`;
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<Me & { token: string; expires_at: number }>;
}

async function read<T>(path: string, example: () => T): Promise<{ data: T; source: Source }> {
  if (isDemo()) return { data: example(), source: { live: false, reason: "API not connected (ANONYMIZER_API_URL)" } };
  return { data: await api<T>(path), source: { live: true } };
}

export const getMe = () => read<Me>("/v1/auth/me", () => exampleMe);
export const getInfo = () => read<Info>("/v1/info", () => exampleInfo);
export const getMetrics = (hours = 24) => read<Metrics>(`/v1/metrics?hours=${hours}`, () => exampleMetrics);
export const getTraces = (limit = 50, route?: string) =>
  read<Trace[]>(`/v1/traces?limit=${limit}${route ? `&route=${encodeURIComponent(route)}` : ""}`,
    () => (route ? exampleTraces.filter(t => t.route === route) : exampleTraces));
export const getTrace = async (id: string) => {
  if (isDemo()) return read<Trace | null>("", () => exampleTraces.find(t => t.id === id) ?? null);
  try {
    return await read<Trace | null>(`/v1/traces/${encodeURIComponent(id)}`, () => null);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { data: null, source: { live: true } };
    throw e;
  }
};
export const getPolicies = () => read<PolicySummary[]>("/v1/policies", () => examplePolicies);
export const getPolicy = (name: string) =>
  read<Record<string, unknown> | null>(`/v1/policies/${encodeURIComponent(name)}`, () => null);
export const getApiKeys = () => read<ApiKey[]>("/v1/api-keys", () => exampleApiKeys);
export const getMembers = () => read<User[]>("/v1/members", () => exampleMembers);
export const getGateway = () => read<GatewayStatus>("/v1/gateway", () => exampleGateway);

export const getSources = () => read<SourcesInfo>("/v1/sources", () => exampleSources);

/** Not-configured features answer 404; pages show a setup hint instead of an error. */
async function optional<T>(path: string, example: () => T): Promise<{ data: T | null; source: Source }> {
  try {
    return await read<T | null>(path, example);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { data: null, source: { live: true } };
    throw e;
  }
}

export const getProxy = () => optional<ProxyStatus>("/v1/proxy", () => exampleProxy);

export const getConversations = (cursor?: string) =>
  optional<ConversationPage>(`/v1/conversations?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    () => exampleConversations);
export const getConversationStats = (groupBy: string) =>
  optional<ConversationStats>(`/v1/conversations/stats?group_by=${encodeURIComponent(groupBy)}`,
    () => ({ ...exampleConversationStats, group_by: groupBy }));
export const getQuota = () =>
  optional<Quota>("/v1/conversations/quota", () => ({ used: 1, limit: 200, remaining: 199 }));
/** Reading a conversation counts against the viewer's daily quota and is written to the audit log. */
export const getConversation = (id: string) =>
  optional<Conversation>(`/v1/conversations/${encodeURIComponent(id)}`,
    () => (exampleConversations.data.some(c => c.id === id) ? { ...exampleConversation, id } : null) as Conversation);

export const getPrompts = () => optional<PromptListItem[]>("/v1/prompts", () => examplePrompts);
export const getPrompt = (name: string, version?: number) =>
  optional<PromptVersion>(`/v1/prompts/${encodeURIComponent(name)}${version ? `?version=${version}` : ""}`,
    () => (examplePrompts.some(p => p.name === name)
      ? { ...examplePromptVersion, name, ...(version ? { version } : {}) } : null) as PromptVersion);
export const getPromptHistory = (name: string) =>
  optional<PromptHistoryItem[]>(`/v1/prompts/${encodeURIComponent(name)}/history`, () => examplePromptHistory);
export const getPromptDiff = (name: string, from: number, to: number) =>
  optional<PromptDiff>(`/v1/prompts/${encodeURIComponent(name)}/diff?from_version=${from}&to_version=${to}`,
    () => ({ name, from, to, config_changed: false, protected: false,
             diff: `--- ${name}@v${from}\n+++ ${name}@v${to}\n@@ -1,2 +1,3 @@\n Du bist der Support-Assistent der Beispiel GmbH.\n-Antworte freundlich.\n+Antworte freundlich und kurz.\n+Frage nach der Bestellnummer, bevor du Auskunft gibst.\n` }));

export type AuditQuery = { before?: string; action?: string; resource_type?: string; limit?: number };
export const getAuditLogs = (q: AuditQuery) => {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries({ limit: 50, ...q })) if (v) params.set(k, String(v));
  return read<AuditPage>(`/v1/audit-logs?${params}`, () => ({
    data: exampleAudit.filter(e => (!q.action || e.action === q.action) && (!q.resource_type || e.resource_type === q.resource_type)),
    next_before: null,
    actions: [...new Set(exampleAudit.map(e => e.action))].sort(),
    resource_types: [...new Set(exampleAudit.map(e => e.resource_type))].sort(),
  }));
};
export const getAuditEntry = (id: string) =>
  read<AuditEntry | null>(`/v1/audit-logs/${encodeURIComponent(id)}`, () => exampleAudit.find(e => e.id === id) ?? null);
export const verifyAudit = () =>
  read<AuditVerify>("/v1/audit-logs/verify", () => ({ ok: true, entries: exampleAudit.length, broken_at: null }));

export const getDatasets = () => read<Dataset[]>("/v1/playground/datasets", () => exampleDatasets);
export const queryDataset = async (id: string, q: { query?: string; limit?: number; offset?: number }) => {
  if (isDemo()) return { data: id === exampleDatasets[0]!.id ? examplePlayground(q.query) : null, source: { live: false, reason: "API not connected (ANONYMIZER_API_URL)" } as Source };
  try {
    return { data: await api<PlaygroundResult>(`/v1/playground/datasets/${encodeURIComponent(id)}/query`, {
      method: "POST", body: JSON.stringify({ query: q.query || null, limit: q.limit ?? 20, offset: q.offset ?? 0 }),
    }), source: { live: true } as Source };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { data: null, source: { live: true } as Source };
    throw e;
  }
};

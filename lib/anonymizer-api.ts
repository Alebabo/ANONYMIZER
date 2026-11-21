import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  exampleApiKeys, exampleAudit, exampleDatasets, exampleInfo, exampleMe, exampleMembers, examplePlayground, examplePolicies,
  exampleSources, exampleTraces,
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
  /** Playground traces (and older MCP proxy traces): source, tool, mode and entity types per JSON field path. */
  upstream?: string | null; tool?: string | null; mode?: string | null;
  fields?: Record<string, Record<string, number>>;
  /** Older MCP proxy traces: characters of the call arguments and of the result handed to the model. */
  args_chars?: number | null; result_chars?: number | null;
  /** What was read, e.g. a playground dataset id. */
  resource?: string | null;
  /** Only with ANONYMIZER_TRACE_CONTENT=1 and for admins: protected text and original values. */
  content?: TraceContent[];
  /** Channel (api | mcp | dashboard) and who called: key name or user e-mail. */
  client?: string | null; actor?: string | null;
};

export type TraceContent = {
  label: string | null; input?: string | null; output: string | null; withheld: boolean;
  replacements: { type: string; original: string; replacement: string | null; method: string | null }[];
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

export type Source = { live: boolean; reason?: string };

export type SourcesInfo = {
  /** Policy used for playground (CSV) queries. */
  playground_policy: string;
  mcp_http: boolean;
};

export type Dataset = {
  id: string; name: string; /** Visible columns only. */ columns: string[]; rows: number; created_at: number; created_by: string | null;
  /** Dashboard sessions only: every column in upload order and the hidden ones. */ all_columns?: string[]; hidden?: string[];
};
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
/** Raw text of an API response (e.g. a JSONL export); same auth and error handling as api(). */
export async function apiText(path: string): Promise<string> {
  const t = await token();
  if (!t) redirect("/login");
  const res = await fetch(`${base()}${path}`, { headers: { Authorization: `Bearer ${t}` }, cache: "no-store" });
  if (res.status === 401) redirect("/login?expired=1");
  if (!res.ok) throw new ApiError(res.status, `OpenAnonymizer API ${res.status}`);
  return res.text();
}

export type FeedbackRow = {
  id: string; created_at: number; created_by: string | null; text: string; policy: string | null; trace_id: string | null;
  spans: { start: number; end: number; kind: "missed" | "wrong"; label: string }[];
};
/** Admins only (raw text); members get null. */
export const getFeedback = async () => {
  if (isDemo()) return { data: [] as FeedbackRow[], source: { live: false, reason: "API not connected (ANONYMIZER_API_URL)" } as Source };
  try {
    return { data: await api<FeedbackRow[]>("/v1/feedback"), source: { live: true } as Source };
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) return { data: null, source: { live: true } as Source };
    throw e;
  }
};

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
export const getTraces = (limit = 50, f: { route?: string; client?: string } = {}) => {
  const q = new URLSearchParams({ limit: String(limit) });
  if (f.route) q.set("route", f.route);
  if (f.client) q.set("client", f.client);
  return read<Trace[]>(`/v1/traces?${q}`,
    () => exampleTraces.filter(t => (!f.route || t.route === f.route) && (!f.client || t.client === f.client)));
};
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

export const getSources = () => read<SourcesInfo>("/v1/sources", () => exampleSources);

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

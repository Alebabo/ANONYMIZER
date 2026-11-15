import "server-only";
import { exampleMetrics, examplePolicies, exampleTraces } from "@/lib/mock";

/**
 * Server-side access to the Cato API. The API key never reaches the browser.
 *
 * Live data is only used when BOTH are true:
 *  - CATO_API_URL and CATO_API_KEY are set, and
 *  - the dashboard itself is protected (CATO_DASHBOARD_USER/PASSWORD, see middleware.ts).
 * Otherwise the pages show clearly labelled example data (fail closed).
 */

export type Trace = {
  id: string; created_at: number; route: string; outcome: string | null; allowed: boolean | null;
  risk: string | null; needs_review: boolean; policy: string | null; policy_hash: string | null;
  destination: string | null; provider: string | null; model: string | null; language: string | null;
  latency_ms: number | null; status: number; error: string | null; entity_counts: Record<string, number>;
  risk_counts: Record<string, number>; actions: Record<string, number>; transformations: number;
  signals: string[]; warnings: string[]; steps: { name: string; detail: string; status: string }[];
};

export type Metrics = {
  window_hours: number; requests: number; requests_with_detections: number; detection_rate: number;
  detections: number; anonymized_entities: number; anonymization_rate: number; not_allowed: number;
  block_rate: number; by_outcome: Record<string, number>; by_risk: Record<string, number>;
  by_route: Record<string, number>; by_provider: Record<string, number>; by_policy: Record<string, number>;
  entity_distribution: Record<string, number>; actions: Record<string, number>;
  latency_ms: { avg: number | null; p95: number | null }; errors: number;
  timeseries: { t: number; requests: number }[];
};

export type PolicySummary = { name: string; version: number; hash: string; scope: Record<string, unknown> };

export type Source = { live: boolean; reason?: string };

export function apiConfigured(): Source {
  const url = process.env.CATO_API_URL;
  const key = process.env.CATO_API_KEY;
  if (!url || !key) return { live: false, reason: "API not connected (CATO_API_URL / CATO_API_KEY)" };
  if (!process.env.CATO_DASHBOARD_USER || !process.env.CATO_DASHBOARD_PASSWORD)
    return { live: false, reason: "Dashboard login not configured; live data disabled" };
  return { live: true };
}

async function call<T>(path: string): Promise<T> {
  const res = await fetch(`${process.env.CATO_API_URL!.replace(/\/$/, "")}${path}`, {
    headers: { Authorization: `Bearer ${process.env.CATO_API_KEY}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Cato API ${res.status}`);
  return res.json() as Promise<T>;
}

async function withFallback<T>(path: string, example: () => T): Promise<{ data: T; source: Source }> {
  const source = apiConfigured();
  if (!source.live) return { data: example(), source };
  try {
    return { data: await call<T>(path), source };
  } catch (e) {
    return { data: example(), source: { live: false, reason: e instanceof Error ? e.message : "API error" } };
  }
}

export const getMetrics = (hours = 24) => withFallback<Metrics>(`/v1/metrics?hours=${hours}`, () => exampleMetrics);
export const getTraces = (limit = 50) => withFallback<Trace[]>(`/v1/traces?limit=${limit}`, () => exampleTraces);
export const getTrace = (id: string) =>
  withFallback<Trace | null>(`/v1/traces/${encodeURIComponent(id)}`, () => exampleTraces.find(t => t.id === id) ?? null);
export const getPolicies = () => withFallback<PolicySummary[]>("/v1/policies", () => examplePolicies);
export const getPolicyYaml = async (name: string) =>
  withFallback<Record<string, unknown> | null>(`/v1/policies/${encodeURIComponent(name)}`, () => null);

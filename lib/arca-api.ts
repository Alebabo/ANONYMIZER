import "server-only";
import { api, isDemo } from "@/lib/anonymizer-api";

/**
 * Server-side access to the local Arca service (arca/src/arca/service.py). The service is the only component
 * that opens vault.db; the browser only talks to it through server actions and this page.
 */

export const ARCA_API_URL = process.env.ARCA_API_URL || "http://127.0.0.1:8100";

export type ArcaColumn = { key: string; label: string; kind: string };
export type ArcaSpan = { start: number; end: number; type: string };
export type ArcaCell = { value: string; spans: ArcaSpan[] };
export type ArcaOptions = { dates: "month" | "year" | "keep"; money: "range" | "keep" };
export type ArcaPreview = {
  id: string; created_at: number; columns: string[]; rows: { zeile: number; cells: Record<string, ArcaCell> }[];
  options: ArcaOptions;
  /** Eigennamen, die nach der Anonymisierung stehen geblieben sind (Pflichtprüfung). */
  hints: number;
};
export type ArcaAudit = {
  id: number; created_at: number; action: string; columns: string[]; row_count: number; preview_id: string | null;
  actor: string | null; details: { options?: ArcaOptions; hints?: number; ocr?: boolean } | null;
};
export type ArcaTables = {
  columns: ArcaColumn[];
  vault: Record<string, string | number>[];
  visible: { columns: string[]; rows: (string | number)[][] };
  released: boolean;
  audit: ArcaAudit[];
  documents: { id: number; mandat_id: number; dateiname: string; format: string; ocr: number; chars: number; created_at: number }[];
  /** Lokales OCR mit Netzwerk-Isolation verfügbar. */
  ocr: boolean;
};

export class ArcaError extends Error {}

/**
 * Login check for the Arca tab and every Arca action. In live mode (ANONYMIZER_API_URL set) the session
 * token is validated by the API (GET /v1/auth/me); a missing or expired session redirects to /login. The
 * middleware alone only checks that a cookie exists. Demo mode (local development) has no login.
 */
export async function requireArcaUser(): Promise<string> {
  if (isDemo()) return "lokal";
  const me = await api<{ user: { email: string } | null }>("/v1/auth/me");
  return me.user?.email ?? "unbekannt";
}

/** WebSocket URL of the terminal. Relative (e.g. "/arca/terminal") = same host as the dashboard, via Caddy. */
export const ARCA_TERMINAL_URL = process.env.ARCA_TERMINAL_URL || "ws://127.0.0.1:8101";

export async function arca<T>(path: string, body?: unknown): Promise<T> {
  await requireArcaUser();
  let res: Response;
  const form = body instanceof FormData;
  try {
    res = await fetch(`${ARCA_API_URL}${path}`, {
      method: body === undefined ? "GET" : "POST", cache: "no-store",
      headers: body === undefined || form ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    });
  } catch {
    throw new ArcaError(`Arca-Service nicht erreichbar (${ARCA_API_URL}). Start: arca-service`);
  }
  if (!res.ok) {
    const detail = await res.json().then(j => j.detail, () => null);
    throw new ArcaError(typeof detail === "string" ? detail : `Arca-Service: HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

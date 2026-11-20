import type { Source } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

export function SourceBanner({ source }: { source: Source }) {
  if (source.live) return null;
  return (
    <div className="bg-light-yellow text-dark-yellow border-b px-4 py-2 text-xs md:px-6">
      Example data · {source.reason}
    </div>
  );
}

export const fmt = (n: number) => n.toLocaleString("en-US");
/** Characters as a short number ("12.3k"); tokens are estimated as characters / 4. */
export const chars = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
export const tokens = (n: number) => chars(Math.round(n / 4));
export const pct = (r: number) => `${(r * 100).toFixed(1)}%`;
export const time = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });

const outcomeStyle: Record<string, string> = {
  allow: "bg-light-green text-dark-green",
  review: "bg-light-yellow text-dark-yellow",
  local_only: "bg-light-yellow text-dark-yellow",
  block: "bg-light-red text-dark-red",
  critical: "bg-light-red text-dark-red",
  sensitive: "bg-light-yellow text-dark-yellow",
  low: "bg-light-green text-dark-green",
  ok: "bg-light-green text-dark-green",
  warning: "bg-light-yellow text-dark-yellow",
  blocked: "bg-light-red text-dark-red",
  enforce: "bg-light-green text-dark-green",
  observe: "bg-light-yellow text-dark-yellow",
  connected: "bg-light-green text-dark-green",
  disconnected: "bg-light-red text-dark-red",
  error: "bg-light-red text-dark-red",
  active: "bg-light-green text-dark-green",
  disabled: "bg-light-red text-dark-red",
  configured: "bg-light-green text-dark-green",
  "not configured": "bg-muted text-muted-foreground",
};

export function Pill({ value }: { value: string | null | undefined }) {
  const v = value ?? "n/a";
  return <span className={cn("inline-flex rounded-md px-2 py-0.5 text-xs", outcomeStyle[v] ?? "bg-muted text-muted-foreground")}>{v}</span>;
}

export const dateTime = (ts: number | null | undefined) =>
  ts == null ? "–" : new Date(ts * 1000).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin",
  });

export function ago(ts: number | null | undefined): string {
  if (ts == null) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

/** Notice shown on management pages for members (read-only) and in demo mode. */
export function Notice({ children }: { children: React.ReactNode }) {
  return <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-xs">{children}</p>;
}

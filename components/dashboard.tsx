import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { Source } from "@/lib/cato-api";
import { cn } from "@/lib/utils";

export function SourceBanner({ source }: { source: Source }) {
  if (source.live) return null;
  return (
    <div className="bg-light-yellow text-dark-yellow border-b px-4 py-2 text-xs md:px-6">
      Example data · {source.reason}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardHeader><CardDescription>{label}</CardDescription></CardHeader>
      <CardContent>
        <div className="text-xl font-bold tabular-nums md:text-2xl">{value}</div>
        {sub && <div className="text-muted-foreground text-xs">{sub}</div>}
      </CardContent>
    </Card>
  );
}

export const fmt = (n: number) => n.toLocaleString("en-US");
export const pct = (r: number) => `${(r * 100).toFixed(1)}%`;
export const time = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });

/** Minimal bar chart (inline SVG), monochrome, accessible summary. */
export function Bars({ series, label }: { series: { t: number; requests: number }[]; label: string }) {
  const max = Math.max(1, ...series.map(s => s.requests));
  const w = 100 / Math.max(series.length, 1);
  const total = series.reduce((a, s) => a + s.requests, 0);
  return (
    <figure>
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-32 w-full md:h-40" role="img"
           aria-label={`${label}: ${fmt(total)} total, peak ${fmt(max)} per hour`}>
        {series.map((s, i) => {
          const h = (s.requests / max) * 38;
          return <rect key={s.t} x={i * w + w * 0.15} y={40 - h} width={w * 0.7} height={h}
                       className="fill-foreground/70"><title>{`${time(s.t)} · ${fmt(s.requests)}`}</title></rect>;
        })}
      </svg>
      <figcaption className="text-muted-foreground mt-1 flex justify-between text-2xs">
        <span>{series[0] ? time(series[0].t) : ""}</span><span>{series.at(-1) ? time(series.at(-1)!.t) : ""}</span>
      </figcaption>
    </figure>
  );
}

/** Horizontal share bars for distributions. */
export function Distribution({ data, empty = "No data" }: { data: Record<string, number>; empty?: string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((a, [, v]) => a + v, 0);
  if (!entries.length) return <p className="text-muted-foreground text-xs">{empty}</p>;
  return (
    <ul className="space-y-2">
      {entries.map(([k, v]) => (
        <li key={k} className="text-xs">
          <div className="flex justify-between"><span>{k}</span><span className="tabular-nums">{fmt(v)} · {pct(v / total)}</span></div>
          <div className="bg-muted mt-1 h-1.5 rounded-sm"><div className="bg-foreground/70 h-1.5 rounded-sm" style={{ width: `${(v / total) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

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
  error: "bg-light-red text-dark-red",
};

export function Pill({ value }: { value: string | null | undefined }) {
  const v = value ?? "n/a";
  return <span className={cn("inline-flex rounded-md px-2 py-0.5 text-xs", outcomeStyle[v] ?? "bg-muted text-muted-foreground")}>{v}</span>;
}

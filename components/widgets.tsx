/* Langfuse-style dashboard widgets (server-renderable, no client JS). */
import Link from "next/link";
import { fmt, pct } from "@/components/dashboard";
import { cn } from "@/lib/utils";

/** Dashboard widget: title, optional description and link in the header, content below. */
export function Widget({ title, description, action, className, children }: {
  title: string; description?: string; action?: { label: string; href: string }; className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("bg-card text-card-foreground flex min-w-0 flex-col rounded-lg border", className)}>
      <header className="flex items-start justify-between gap-2 px-4 pt-3 pb-2">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium">{title}</h2>
          {description && <p className="text-muted-foreground text-xs">{description}</p>}
        </div>
        {action && <Link href={action.href} className="text-link hover:text-link-hover shrink-0 text-xs">{action.label}</Link>}
      </header>
      <div className="min-w-0 flex-1 px-4 pb-4">{children}</div>
    </section>
  );
}

/** Change against the previous window of the same length. `good` says which direction is desirable. */
export function Delta({ now, prev, good = "neutral" }: { now: number; prev: number | undefined; good?: "up" | "down" | "neutral" }) {
  if (prev == null) return null;
  if (prev === 0 && now === 0) return <span className="text-muted-foreground">±0</span>;
  const up = now > prev;
  const tone = good === "neutral" || now === prev ? "text-muted-foreground"
    : (up === (good === "up")) ? "text-dark-green" : "text-dark-red";
  const label = prev === 0 ? "new" : `${up ? "+" : now < prev ? "−" : "±"}${Math.abs(((now - prev) / prev) * 100).toFixed(0)}%`;
  return <span className={cn("tabular-nums", tone)} title={`Previous window: ${fmt(prev)}`}>{label}</span>;
}

export type DotState = "ok" | "warn" | "error" | "off";
const dotStyle: Record<DotState, string> = {
  ok: "bg-dark-green", warn: "bg-dark-yellow", error: "bg-dark-red", off: "bg-foreground-tertiary",
};
export function Dot({ state }: { state: DotState }) {
  return <span aria-hidden className={cn("inline-block h-2 w-2 shrink-0 rounded-full", dotStyle[state])} />;
}

/** KPI tile: label, big number, change, one line of context. */
export function Kpi({ label, value, sub, delta, tone, href }: {
  label: string; value: string; sub?: React.ReactNode; delta?: React.ReactNode; tone?: DotState; href?: string;
}) {
  const body = (
    <>
      <div className="text-muted-foreground flex items-center gap-1.5 text-xs">{tone && <Dot state={tone} />}{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums">{value}</span>
        {delta && <span className="text-xs">{delta}</span>}
      </div>
      {sub && <div className="text-muted-foreground mt-0.5 truncate text-xs">{sub}</div>}
    </>
  );
  const cls = "bg-card block min-w-0 rounded-lg border px-4 py-3";
  return href ? <Link href={href} className={cn(cls, "hover:border-border-contrast")}>{body}</Link> : <div className={cls}>{body}</div>;
}

export type StatusItem = { label: string; state: DotState; detail: string; href?: string };
/** Health checklist: one line per component, colored dot, short state. */
export function StatusList({ items }: { items: StatusItem[] }) {
  return (
    <ul className="divide-y text-xs">
      {items.map(i => (
        <li key={i.label} className="flex items-center gap-2 py-1.5">
          <Dot state={i.state} />
          <span className="w-28 shrink-0 font-medium">{i.label}</span>
          {i.href
            ? <Link href={i.href} className="text-muted-foreground hover:text-foreground min-w-0 flex-1 truncate" title={i.detail}>{i.detail}</Link>
            : <span className="text-muted-foreground min-w-0 flex-1 truncate" title={i.detail}>{i.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Horizontal bar list (Tremor BarList look): label inside a tinted bar, value on the right. */
export function BarList({ data, color = "--chart-fill-1", empty = "No data", limit = 8, mono = false }: {
  data: Record<string, number>; color?: string; empty?: string; limit?: number; mono?: boolean;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <p className="text-muted-foreground py-6 text-center text-xs">{empty}</p>;
  const max = entries[0]![1] || 1;
  const total = entries.reduce((a, [, v]) => a + v, 0);
  const rest = entries.slice(limit);
  return (
    <ul className="space-y-1">
      {entries.slice(0, limit).map(([k, v]) => (
        <li key={k} className="flex items-center gap-3 text-xs">
          <div className="relative h-6 min-w-0 flex-1">
            <div className="absolute inset-y-0 left-0 rounded-sm"
                 style={{ width: `${Math.max(2, (v / max) * 100)}%`, background: `hsl(var(${color}) / 0.35)` }} />
            <span className={cn("relative flex h-6 items-center truncate px-2", mono && "font-mono")} title={k}>{k}</span>
          </div>
          <span className="w-28 shrink-0 text-right tabular-nums">{fmt(v)} <span className="text-muted-foreground">{pct(v / total)}</span></span>
        </li>
      ))}
      {rest.length > 0 && (
        <li className="text-muted-foreground px-2 text-xs">+ {rest.length} more · {fmt(rest.reduce((a, [, v]) => a + v, 0))}</li>
      )}
    </ul>
  );
}

export const SERIES = [
  { key: "clean", label: "No personal data", color: "hsl(var(--chart-fill-1))" },
  { key: "anonymized", label: "Anonymized", color: "hsl(var(--chart-3))" },
  { key: "not_allowed", label: "Not sent", color: "hsl(var(--chart-5))" },
  { key: "errors", label: "Errors", color: "hsl(var(--destructive))" },
] as const;

type SeriesKey = (typeof SERIES)[number]["key"];
type Point = { t: number; requests: number } & Partial<Record<SeriesKey, number>>;

const bucketLabel = (t: number, step: number) => new Date(t * 1000).toLocaleString("de-DE",
  step >= 86400 ? { day: "2-digit", month: "2-digit", timeZone: "Europe/Berlin" }
    : { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" });

function niceMax(v: number) {
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/** Stacked bars per time bucket: what happened to each request. Falls back to totals for older APIs. */
export function StackedBars({ series, step = 3600 }: { series: Point[]; step?: number }) {
  const split = series.some(s => s.clean != null);
  const max = Math.max(1, ...series.map(s => s.requests));
  const top = niceMax(max);
  const w = 100 / Math.max(series.length, 1);
  const total = series.reduce((a, s) => a + s.requests, 0);
  const ticks = [...new Set([0, Math.floor(series.length / 3), Math.floor((series.length * 2) / 3), series.length - 1])]
    .filter(i => i >= 0);
  return (
    <figure>
      <div className="flex gap-2">
        <div className="text-muted-foreground flex h-44 w-8 shrink-0 flex-col justify-between text-right text-2xs tabular-nums md:h-64">
          <span>{fmt(top)}</span><span>{fmt(top / 2)}</span><span>0</span>
        </div>
        <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-44 min-w-0 flex-1 md:h-64" role="img"
             aria-label={`Requests over time: ${fmt(total)} total, peak ${fmt(max)} per bucket`}>
          {[0.05, 20, 39.95].map(y => (
            <line key={y} x1="0" x2="100" y1={y} y2={y} stroke="hsl(var(--chart-grid))" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          {series.map((s, i) => {
            let y = 40;
            const parts = split ? SERIES.map(c => ({ key: c.key, color: c.color, v: s[c.key] ?? 0 }))
              : [{ key: "requests", color: SERIES[0].color, v: s.requests }];
            const tip = `${bucketLabel(s.t, step)} · ${fmt(s.requests)} requests` +
              (split ? "\n" + SERIES.map(c => `${c.label}: ${fmt(s[c.key] ?? 0)}`).join("\n") : "");
            return (
              <g key={s.t}>
                <title>{tip}</title>
                <rect x={i * w} y={0} width={w} height={40} fill="transparent" />
                {parts.map(p => {
                  const h = (p.v / top) * 40;
                  y -= h;
                  return h > 0 ? <rect key={p.key} x={i * w + w * 0.12} y={y} width={w * 0.76} height={h} fill={p.color} /> : null;
                })}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="text-muted-foreground relative mt-1 ml-10 h-4 text-2xs">
        {ticks.map(i => series[i] && (
          <span key={i} className="absolute -translate-x-1/2 tabular-nums whitespace-nowrap" style={{ left: `${(i + 0.5) * w}%` }}>
            {bucketLabel(series[i]!.t, step)}
          </span>
        ))}
      </div>
      {split && (
        <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {SERIES.map(c => (
            <span key={c.key} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c.color }} />
              {c.label}
              <span className="text-muted-foreground tabular-nums">{fmt(series.reduce((a, s) => a + (s[c.key] ?? 0), 0))}</span>
            </span>
          ))}
        </figcaption>
      )}
    </figure>
  );
}

/** Segmented 100% bar with legend, e.g. risk mix of requests. */
export function SegmentBar({ data, colors, order }: { data: Record<string, number>; colors: Record<string, string>; order?: string[] }) {
  const entries = Object.entries(data).filter(([, v]) => v > 0)
    .sort((a, b) => (order ? order.indexOf(a[0]) - order.indexOf(b[0]) : b[1] - a[1]));
  const total = entries.reduce((a, [, v]) => a + v, 0);
  if (!total) return <p className="text-muted-foreground text-xs">No data</p>;
  const color = (k: string) => colors[k] ?? "hsl(var(--muted-gray))";
  return (
    <div>
      <div className="flex h-2 gap-px overflow-hidden rounded-full">
        {entries.map(([k, v]) => <div key={k} title={`${k}: ${fmt(v)}`} style={{ width: `${(v / total) * 100}%`, background: color(k) }} />)}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {entries.map(([k, v]) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color(k) }} />
            {k} <span className="text-muted-foreground tabular-nums">{fmt(v)} · {pct(v / total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const ms = (v: number | null | undefined) =>
  v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;

export const stamp = (ts: number) => new Date(ts * 1000).toLocaleString("de-DE", {
  day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Berlin",
});

/** Langfuse-style metadata chip, e.g. "Latency: 182 ms". */
export function Chip({ label, children, className }: { label?: string; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("bg-muted text-foreground-secondary inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs whitespace-nowrap", className)}>
      {label && <span className="text-muted-foreground">{label}:</span>}{children}
    </span>
  );
}

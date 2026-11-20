/* Langfuse-style dashboard widgets (server-renderable, no client JS). */
import Link from "next/link";
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

export type DotState = "ok" | "warn" | "error" | "off";
const dotStyle: Record<DotState, string> = {
  ok: "bg-dark-green", warn: "bg-dark-yellow", error: "bg-dark-red", off: "bg-foreground-tertiary",
};
export function Dot({ state }: { state: DotState }) {
  return <span aria-hidden className={cn("inline-block h-2 w-2 shrink-0 rounded-full", dotStyle[state])} />;
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

/**
 * Collapsed by default: details, audit and trace information that most people do not need every time.
 * Native <details>, so it works without client JS and is keyboard accessible.
 */
export function Collapsible({ title, summary, defaultOpen, className, children }: {
  title: string; summary?: React.ReactNode; defaultOpen?: boolean; className?: string; children: React.ReactNode;
}) {
  return (
    <details open={defaultOpen} className={cn("group bg-card min-w-0 rounded-lg border", className)}>
      <summary className="hover:bg-muted/50 flex cursor-pointer list-none items-center gap-2 rounded-lg px-4 py-2.5 text-sm [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-muted-foreground inline-block w-3 transition-transform group-open:rotate-90">›</span>
        <span className="font-medium">{title}</span>
        {summary && <span className="text-muted-foreground ml-auto truncate text-xs">{summary}</span>}
      </summary>
      <div className="min-w-0 space-y-3 px-4 pb-4">{children}</div>
    </details>
  );
}

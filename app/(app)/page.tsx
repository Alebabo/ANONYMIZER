import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { PageHeader } from "@/components/app-shell";
import { SourceBanner, ago, fmt, pct } from "@/components/dashboard";
import { RangePicker } from "@/components/range-picker";
import { BarList, Delta, Kpi, StackedBars, Widget, stamp, type StatusItem } from "@/components/widgets";
import {
  getInfo, getMetrics, getProxy, getQuota, getSources, getTraces, verifyAudit, type Trace,
} from "@/lib/anonymizer-api";
import { rangeFor } from "@/lib/ranges";

export const dynamic = "force-dynamic";

/** A failing side call (e.g. audit verify for non-admins) must not take the whole dashboard down. */
async function safe<T>(p: Promise<{ data: T }>): Promise<T | null> {
  try { return (await p).data; } catch (e) { unstable_rethrow(e); return null; }
}

const attention = (t: Trace) =>
  t.status >= 500 || (t.outcome && t.outcome !== "allow") || t.needs_review || t.warnings.length > 0 || t.mode === "observe" || t.mode === "log";

const why = (t: Trace) =>
  t.status >= 500 ? `error ${t.status}` : t.needs_review ? "needs review" : t.outcome && t.outcome !== "allow" ? t.outcome
    : t.mode === "observe" || t.mode === "log" ? `${t.mode} mode: sent unchanged` : t.warnings[0] ?? "warning";

const opName = (t: Trace) => (t.upstream && t.tool ? `${t.upstream}__${t.tool}` : t.route);

export default async function Home({ searchParams }: { searchParams: Promise<{ range?: string }> }) {
  const range = rangeFor((await searchParams).range);
  const [{ data: m, source }, traces, info, sources, proxy, quota, audit] = await Promise.all([
    getMetrics(range.hours), safe(getTraces(100)), safe(getInfo()), safe(getSources()), safe(getProxy()),
    safe(getQuota()), safe(verifyAudit()),
  ]);
  const prev = m.previous;
  const recent = traces ?? [];
  const flagged = recent.filter(attention).slice(0, 6);

  // -- System status: everything that must be true before anyone trusts the numbers below ----------
  const status: StatusItem[] = [];
  const conv = sources?.conversations;
  status.push(conv
    ? { label: "Data source", state: "ok", detail: `${conv.kind} · ${conv.location} · ${conv.daily_limit}/day per user`, href: "/conversations" }
    : { label: "Data source", state: "off", detail: "No conversation source (ANONYMIZER_SOURCE)" });
  status.push({ label: "MCP for Claude", state: sources?.mcp_http ? "ok" : "off",
                detail: sources?.mcp_http ? "/mcp enabled" : "HTTP MCP off (ANONYMIZER_MCP_HTTP)", href: "/proxy" });
  if (proxy) {
    for (const u of proxy.upstreams) {
      status.push({ label: `Proxy · ${u.name}`, href: "/proxy",
        state: !u.connected ? "error" : u.mode !== "enforce" ? "warn" : "ok",
        detail: !u.connected ? (u.error ?? "disconnected")
          : `${u.mode}${u.mode !== "enforce" ? " (data passes unchanged)" : ""} · ${u.tools_exposed}/${u.tools_upstream} tools · ${u.policy}` });
    }
  } else {
    status.push({ label: "MCP proxy", state: "off", detail: "Not configured", href: "/proxy" });
  }
  if (info) {
    status.push({ label: "Name detection", state: info.ner === "available" ? "ok" : info.ner === "disabled" ? "warn" : "error",
      detail: info.ner === "available" ? "NER model loaded" : info.ner === "disabled" ? "NER disabled: names only found by rules"
        : "NER model missing: names may pass unredacted" });
    status.push({ label: "Default policy", state: "ok", detail: info.default_policy, href: "/settings/policies" });
    status.push({ label: "Content traces", state: info.trace_content ? "warn" : "ok",
      detail: info.trace_content ? "ON: original values stored in clear text (test data only)" : "Off: metadata only" });
    status.push({ label: "Retention", state: "ok", detail: `Traces kept ${info.trace_retention_days ?? "–"} days` });
  }
  status.push(audit
    ? { label: "Audit chain", state: audit.ok ? "ok" : "error", href: "/settings/audit-logs",
        detail: audit.ok ? `${fmt(audit.entries)} entries, hash chain intact` : `Broken at ${audit.broken_at}` }
    : { label: "Audit chain", state: "off", detail: "Verification for admins only", href: "/settings/audit-logs" });
  status.push({ label: "Last request", state: m.last_trace_at ? "ok" : "off", detail: m.last_trace_at ? ago(m.last_trace_at) : "No traffic yet" });

  // -- Alerts: problems in config plus things that happened in the window ----------------------------
  const alerts: { text: string; href: string; severe: boolean }[] = [
    ...status.filter(s => s.state === "error" || s.state === "warn")
      .map(s => ({ text: `${s.label}: ${s.detail}`, href: s.href ?? "/", severe: s.state === "error" })),
  ];
  if (m.errors) alerts.push({ text: `${fmt(m.errors)} request(s) failed with a server error`, href: "/traces", severe: true });
  if (m.needs_review) alerts.push({ text: `${fmt(m.needs_review)} request(s) held for review`, href: "/traces", severe: false });
  if (m.with_warnings) alerts.push({ text: `${fmt(m.with_warnings)} request(s) with detection warnings`, href: "/traces", severe: false });
  if (quota && quota.limit && quota.used / quota.limit >= 0.8)
    alerts.push({ text: `Daily conversation quota at ${quota.used}/${quota.limit}`, href: "/conversations", severe: quota.remaining === 0 });

  return (
    <>
      <PageHeader title="Home" description="What passed through OpenAnonymizer, what was protected and whether the setup is healthy."
                  meta={m.last_trace_at ? <>Last request {ago(m.last_trace_at)}</> : undefined}>
        <RangePicker value={range.key} />
      </PageHeader>
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        {alerts.length === 0 && (
          <Link href="/proxy" className="bg-light-green text-dark-green flex items-center gap-2 rounded-lg px-4 py-2 text-xs">
            <CheckCircle2 className="h-4 w-4" />All systems ok · {status.filter(s => s.state === "ok").length} checks passed
          </Link>
        )}
        {alerts.length > 0 && (
          <section aria-label="Needs attention" className="bg-card rounded-lg border">
            <header className="flex items-center gap-2 border-b px-4 py-2 text-sm font-medium">
              <AlertTriangle className="text-dark-yellow h-4 w-4" />Needs attention
              <span className="text-muted-foreground text-xs">{alerts.length}</span>
            </header>
            <ul className="divide-y text-xs">
              {alerts.sort((a, b) => Number(b.severe) - Number(a.severe)).map(a => (
                <li key={a.text}>
                  <Link href={a.href} className="hover:bg-muted/50 flex items-center gap-2 px-4 py-1.5">
                    <span className={a.severe ? "bg-dark-red h-2 w-2 rounded-full" : "bg-dark-yellow h-2 w-2 rounded-full"} />
                    {a.text}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Kpi label="Requests" value={fmt(m.requests)} href="/traces"
               delta={<Delta now={m.requests} prev={prev?.requests} />}
               sub={`${pct(m.detection_rate)} contained personal data`} />
          <Kpi label="Personal data found" value={fmt(m.detections)} href="/traces"
               delta={<Delta now={m.detections} prev={prev?.detections} />}
               sub={`${pct(m.anonymization_rate)} anonymized · ${fmt(m.anonymized_entities)} values replaced`} />
          <Kpi label="Not sent" value={fmt(m.not_allowed)} href="/traces" tone={m.not_allowed ? "warn" : undefined}
               delta={<Delta now={m.not_allowed} prev={prev?.not_allowed} good="down" />}
               sub={`${fmt(m.needs_review ?? 0)} review · ${fmt((m.by_outcome.local_only ?? 0) + (m.by_outcome.block ?? 0))} withheld`} />
          <Kpi label="Errors" value={fmt(m.errors)} href="/traces" tone={m.errors ? "error" : "ok"}
               delta={<Delta now={m.errors} prev={prev?.errors} good="down" />}
               sub={m.requests ? `${(100 * m.errors / m.requests).toFixed(2)}% of requests` : "no requests"} />
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <Widget className="xl:col-span-2" title="Requests"
                  description={`What happened to each request · per ${(m.bucket_seconds ?? 3600) >= 86400 ? "day" : "hour"}`}
                  action={{ label: "Traces", href: "/traces" }}>
            <StackedBars series={m.timeseries} step={m.bucket_seconds ?? 3600} />
          </Widget>
          <Widget title="Personal data by type" description={`${fmt(m.detections)} values detected`}>
            <BarList data={m.entity_distribution} color="--chart-fill-3" empty="No personal data detected" />
          </Widget>
        </div>

        <Widget title="Flagged requests" description="Latest not sent, failed, under review or unchanged" action={{ label: "All traces", href: "/traces" }}>
          <ul className="divide-y text-xs">
            {flagged.map(t => (
              <li key={t.id}>
                <Link href={`/traces/${t.id}`} className="hover:bg-muted/50 -mx-2 flex items-center gap-2 rounded-sm px-2 py-1.5">
                  <span className="text-muted-foreground w-28 shrink-0 tabular-nums">{stamp(t.created_at)}</span>
                  <span className="min-w-0 flex-1 truncate font-mono">{opName(t)}</span>
                  <span className="text-muted-foreground shrink-0">{why(t)}</span>
                </Link>
              </li>
            ))}
            {!flagged.length && <li className="text-muted-foreground py-6 text-center">Nothing flagged in the latest {recent.length} traces</li>}
          </ul>
        </Widget>
      </div>
    </>
  );
}

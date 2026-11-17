import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Pill, SourceBanner, ago, fmt, pct } from "@/components/dashboard";
import { RangePicker } from "@/components/range-picker";
import {
  BarList, Chip, Delta, Kpi, SegmentBar, StackedBars, StatusList, Widget, ms, stamp, type StatusItem,
} from "@/components/widgets";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  getGateway, getInfo, getMetrics, getProxy, getQuota, getSources, getTraces, verifyAudit, type Trace,
} from "@/lib/anonymizer-api";
import { rangeFor } from "@/lib/ranges";

export const dynamic = "force-dynamic";

/** A failing side call (e.g. audit verify for non-admins) must not take the whole dashboard down. */
async function safe<T>(p: Promise<{ data: T }>): Promise<T | null> {
  try { return (await p).data; } catch (e) { unstable_rethrow(e); return null; }
}

const OUTCOME_COLORS: Record<string, string> = {
  allow: "hsl(var(--chart-3))", review: "hsl(var(--chart-5))", local_only: "hsl(var(--chart-2))", block: "hsl(var(--destructive))",
};
const RISK_COLORS: Record<string, string> = {
  low: "hsl(var(--chart-fill-1))", sensitive: "hsl(var(--chart-5))", critical: "hsl(var(--destructive))",
};

const attention = (t: Trace) =>
  t.status >= 500 || (t.outcome && t.outcome !== "allow") || t.needs_review || t.warnings.length > 0 || t.mode === "observe";

const why = (t: Trace) =>
  t.status >= 500 ? `error ${t.status}` : t.needs_review ? "needs review" : t.outcome && t.outcome !== "allow" ? t.outcome
    : t.mode === "observe" ? "observe mode: sent unchanged" : t.warnings[0] ?? "warning";

const opName = (t: Trace) => (t.upstream && t.tool ? `${t.upstream}__${t.tool}` : t.route);

export default async function Home({ searchParams }: { searchParams: Promise<{ range?: string }> }) {
  const range = rangeFor((await searchParams).range);
  const [{ data: m, source }, traces, info, sources, proxy, gateway, quota, audit] = await Promise.all([
    getMetrics(range.hours), safe(getTraces(100)), safe(getInfo()), safe(getSources()), safe(getProxy()),
    safe(getGateway()), safe(getQuota()), safe(verifyAudit()),
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
                detail: sources?.mcp_http ? "/mcp enabled" : "HTTP MCP off (ANONYMIZER_MCP_HTTP)", href: "/integrations" });
  if (proxy) {
    for (const u of proxy.upstreams) {
      status.push({ label: `Proxy · ${u.name}`, href: "/proxy",
        state: !u.connected ? "error" : u.mode === "observe" ? "warn" : "ok",
        detail: !u.connected ? (u.error ?? "disconnected")
          : `${u.mode}${u.mode === "observe" ? " (data passes unchanged)" : ""} · ${u.tools_exposed}/${u.tools_upstream} tools · ${u.policy}` });
    }
  } else {
    status.push({ label: "MCP proxy", state: "off", detail: "Not configured", href: "/proxy" });
  }
  status.push(gateway?.external
    ? { label: "LLM gateway", state: "ok", detail: `${gateway.external.provider} · ${gateway.external.host}`, href: "/gateway" }
    : { label: "LLM gateway", state: "off", detail: "No external provider", href: "/gateway" });
  if (info) {
    status.push({ label: "Name detection", state: info.ner === "available" ? "ok" : info.ner === "disabled" ? "warn" : "error",
      detail: info.ner === "available" ? "NER model loaded" : info.ner === "disabled" ? "NER disabled: names only found by rules"
        : "NER model missing: names may pass unredacted" });
    status.push({ label: "Default policy", state: "ok", detail: info.default_policy, href: "/policies" });
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

  const ops = m.by_operation ?? Object.entries(m.by_route).map(([name, calls]) => ({
    name, calls, entities: 0, not_allowed: 0, errors: 0, observe: 0, p95_ms: null as number | null }));

  return (
    <>
      <PageHeader title="Home" description="What passed through Anonymizer, what was protected and whether the setup is healthy."
                  meta={m.last_trace_at ? <>Last request {ago(m.last_trace_at)}</> : undefined}>
        <RangePicker value={range.key} />
      </PageHeader>
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
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

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Kpi label="Requests" value={fmt(m.requests)} href="/traces"
               delta={<Delta now={m.requests} prev={prev?.requests} />}
               sub={`${pct(m.detection_rate)} contained personal data`} />
          <Kpi label="Personal data found" value={fmt(m.detections)} href="/privacy"
               delta={<Delta now={m.detections} prev={prev?.detections} />}
               sub={m.entities_per_request ? `Ø ${m.entities_per_request} per affected request` : "values detected"} />
          <Kpi label="Anonymized" value={pct(m.anonymization_rate)} href="/privacy"
               sub={`${fmt(m.anonymized_entities)} values replaced`} />
          <Kpi label="Not sent" value={fmt(m.not_allowed)} href="/traces" tone={m.not_allowed ? "warn" : undefined}
               delta={<Delta now={m.not_allowed} prev={prev?.not_allowed} good="down" />}
               sub={`${fmt(m.needs_review ?? 0)} review · ${fmt((m.by_outcome.local_only ?? 0) + (m.by_outcome.block ?? 0))} withheld`} />
          <Kpi label="Conversations read" value={fmt(m.resources_read ?? 0)} href="/conversations"
               sub={quota ? `Today ${quota.used} / ${quota.limit} of your quota` : "distinct ids in window"} />
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
          <Widget title="System status" description="Must be green before the numbers count">
            <StatusList items={status} />
          </Widget>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Widget title="Personal data by type" description={`${fmt(m.detections)} values detected`} action={{ label: "Details", href: "/privacy" }}>
            <BarList data={m.entity_distribution} color="--chart-fill-3" empty="No personal data detected" />
          </Widget>
          <Widget title="Where it was found" description="JSON fields with most detections (MCP proxy)">
            <BarList data={m.top_fields ?? {}} color="--chart-fill-4" mono empty="Field paths are recorded for MCP proxy calls" />
          </Widget>
          <Widget title="Decisions" description="Policy outcome and risk per request">
            <div className="space-y-5">
              <div>
                <div className="text-muted-foreground mb-1.5 text-xs">Outcome</div>
                <SegmentBar data={m.by_outcome} colors={OUTCOME_COLORS} order={["allow", "review", "local_only", "block"]} />
              </div>
              <div>
                <div className="text-muted-foreground mb-1.5 text-xs">Risk</div>
                <SegmentBar data={m.by_risk} colors={RISK_COLORS} order={["low", "sensitive", "critical"]} />
              </div>
              <div>
                <div className="text-muted-foreground mb-1.5 text-xs">Actions on values</div>
                <BarList data={m.actions} color="--chart-fill-6" limit={4} empty="No actions" />
              </div>
            </div>
          </Widget>
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <Widget className="xl:col-span-2" title="Operations" description={`Latency p50 ${ms(m.latency_ms.p50)} · p95 ${ms(m.latency_ms.p95)} · p99 ${ms(m.latency_ms.p99)}`}>
            <TableScroll minWidth={560}>
              <Table>
                <TableHeader><TableRow>
                  <TableHead className="w-[40%]">Name</TableHead><TableHead className="text-right">Calls</TableHead>
                  <TableHead className="text-right">Entities</TableHead><TableHead className="text-right">Not sent</TableHead>
                  <TableHead className="text-right">Errors</TableHead><TableHead className="text-right">p95</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {ops.map(o => (
                    <TableRow key={o.name} className="h-8">
                      <TableCell className="truncate font-mono" title={o.name}>
                        {o.name}{o.observe > 0 && <> <Pill value="observe" /></>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(o.calls)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(o.entities)}</TableCell>
                      <TableCell className="text-right tabular-nums">{o.not_allowed ? fmt(o.not_allowed) : <span className="text-muted-foreground">0</span>}</TableCell>
                      <TableCell className={o.errors ? "text-dark-red text-right tabular-nums" : "text-muted-foreground text-right tabular-nums"}>{fmt(o.errors)}</TableCell>
                      <TableCell className="text-right tabular-nums">{ms(o.p95_ms)}</TableCell>
                    </TableRow>
                  ))}
                  {!ops.length && <TableRow><TableCell colSpan={6} className="text-muted-foreground py-6 text-center">No requests in this window</TableCell></TableRow>}
                </TableBody>
              </Table>
            </TableScroll>
          </Widget>
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

        <Widget title="Recent traces" action={{ label: "Open traces", href: "/traces" }}>
          <TableScroll minWidth={720}>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="w-36">Timestamp</TableHead><TableHead>Name</TableHead><TableHead className="w-28">Outcome</TableHead>
                <TableHead>Personal data</TableHead><TableHead className="w-24 text-right">Latency</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {recent.slice(0, 8).map(t => (
                  <TableRow key={t.id} className="h-9">
                    <TableCell className="tabular-nums">{stamp(t.created_at)}</TableCell>
                    <TableCell className="truncate">
                      <Link className="text-link hover:text-link-hover font-mono" href={`/traces/${t.id}`}>{opName(t)}</Link>
                      {t.resource && <span className="text-muted-foreground font-mono"> · {t.resource}</span>}
                    </TableCell>
                    <TableCell><Pill value={t.outcome} /></TableCell>
                    <TableCell className="truncate">
                      <span className="flex gap-1 overflow-hidden">
                        {Object.entries(t.entity_counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => <Chip key={k}>{k} {n}</Chip>)}
                        {!Object.keys(t.entity_counts).length && <span className="text-muted-foreground">–</span>}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{ms(t.latency_ms)}</TableCell>
                  </TableRow>
                ))}
                {!recent.length && <TableRow><TableCell colSpan={5} className="text-muted-foreground py-6 text-center">No traces yet</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableScroll>
        </Widget>
      </div>
    </>
  );
}

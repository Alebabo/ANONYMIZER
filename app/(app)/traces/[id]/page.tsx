import { notFound } from "next/navigation";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Pill, SourceBanner } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getTrace } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function TraceDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { data: t, source } = await getTrace(id);
  if (!t) notFound();
  const dt = new Date(t.created_at * 1000).toLocaleString("de-DE", { timeZone: "Europe/Berlin" });
  return (
    <>
      <PageHeader title={`Trace ${t.id}`} description={`${t.route} · ${dt}`}><Pill value={t.outcome} /></PageHeader>
      <SourceBanner source={source} />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader><CardDescription>Decision history</CardDescription></CardHeader>
          <CardContent>
            <ol className="border-l pl-4">
              {t.steps.map((s, i) => (
                <li key={i} className="relative pb-4">
                  <span className={cn("absolute top-1.5 -left-[21px] h-2.5 w-2.5 rounded-full border-2 border-background",
                    s.status === "ok" ? "bg-dark-green" : s.status === "warning" ? "bg-dark-yellow" : "bg-dark-red")} />
                  <div className="text-sm font-medium">{s.name}</div>
                  <div className="text-muted-foreground text-xs">{s.detail}</div>
                </li>))}
            </ol>
            {!t.content?.length && (
              <p className="text-muted-foreground border-t pt-3 text-xs">
                No content stored for this trace. Content traces are off by default; with
                ANONYMIZER_TRACE_CONTENT=1 admins see what went through and which values were replaced.
              </p>)}
          </CardContent></Card>
        {!!t.content?.length && (
          <Card className="lg:col-span-3"><CardHeader><CardDescription>What went through</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-dark-yellow text-xs">
                Content trace: shows original values in clear text. Use with test data only (ANONYMIZER_TRACE_CONTENT=1).
              </p>
              {t.content.map((c, i) => (
                <div key={i} className="space-y-2 border-t pt-3 first:border-t-0 first:pt-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono break-all">{c.label ?? `#${i + 1}`}</span>
                    {c.withheld && <Pill value="withheld" />}
                  </div>
                  <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap break-words">
                    {c.output ?? "– not sent (withheld by policy) –"}</pre>
                  {c.replacements.length > 0 && (
                    <TableScroll minWidth={420}><Table><TableHeader><TableRow>
                      <TableHead>Type</TableHead><TableHead>Original</TableHead><TableHead>Sent as</TableHead><TableHead>Method</TableHead>
                    </TableRow></TableHeader>
                      <TableBody>{c.replacements.map((r, j) => (
                        <TableRow key={j}>
                          <TableCell>{r.type}</TableCell>
                          <TableCell className="font-mono break-all">{r.original}</TableCell>
                          <TableCell className="font-mono break-all">{r.replacement ?? "withheld"}</TableCell>
                          <TableCell>{r.method ?? "–"}</TableCell>
                        </TableRow>))}
                      </TableBody></Table></TableScroll>)}
                </div>))}
            </CardContent></Card>)}
        <div className="space-y-4">
          <Card><CardHeader><CardDescription>Summary</CardDescription></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                {t.upstream && <>
                  <dt className="text-muted-foreground">Upstream</dt><dd className="font-mono">{t.upstream}</dd>
                  <dt className="text-muted-foreground">Tool</dt><dd className="font-mono break-all">{t.tool}</dd>
                  <dt className="text-muted-foreground">Mode</dt><dd><Pill value={t.mode} /></dd>
                </>}
                {t.resource && <>
                  <dt className="text-muted-foreground">Resource</dt><dd className="font-mono break-all">{t.resource}</dd>
                </>}
                <dt className="text-muted-foreground">Risk</dt><dd><Pill value={t.risk} />{t.needs_review && " · needs review"}</dd>
                <dt className="text-muted-foreground">Policy</dt><dd className="break-all">{t.policy ?? "–"}</dd>
                <dt className="text-muted-foreground">Hash</dt><dd className="font-mono break-all">{t.policy_hash?.slice(0, 23) ?? "–"}</dd>
                <dt className="text-muted-foreground">Destination</dt><dd>{t.destination ?? "–"}</dd>
                <dt className="text-muted-foreground">Provider</dt><dd>{t.provider ? `${t.provider} · ${t.model ?? ""}` : "–"}</dd>
                <dt className="text-muted-foreground">Latency</dt><dd>{t.latency_ms != null ? `${t.latency_ms} ms` : "–"}</dd>
                <dt className="text-muted-foreground">Status</dt><dd>{t.status}{t.error ? ` · ${t.error}` : ""}</dd>
                <dt className="text-muted-foreground">Signals</dt><dd>{t.signals.join(", ") || "–"}</dd>
              </dl>
            </CardContent></Card>
          <Card><CardHeader><CardDescription>Entities & actions</CardDescription></CardHeader>
            <CardContent>
              <ul className="space-y-1 text-xs">
                {Object.entries(t.actions).map(([k, n]) => {
                  const [type, action] = k.split(":");
                  return <li key={k} className="flex justify-between"><span>{type}</span><span>{n} × {action}</span></li>;
                })}
                {!Object.keys(t.actions).length && <li className="text-muted-foreground">No entities</li>}
              </ul>
              {t.warnings.length > 0 && <p className="text-dark-yellow mt-3 text-xs">{t.warnings.join(" · ")}</p>}
            </CardContent></Card>
          {t.fields && Object.keys(t.fields).length > 0 && (
            <Card><CardHeader><CardDescription>Fields with personal data</CardDescription></CardHeader>
              <CardContent>
                <ul className="space-y-1.5 text-xs">
                  {Object.entries(t.fields).map(([path, counts]) => (
                    <li key={path}>
                      <div className="font-mono break-all">{path}</div>
                      <div className="text-muted-foreground">{Object.entries(counts).map(([k, n]) => `${k} ${n}`).join(" · ")}</div>
                    </li>))}
                </ul>
              </CardContent></Card>
          )}
        </div>
      </div>
    </>
  );
}

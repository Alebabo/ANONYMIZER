import { notFound } from "next/navigation";
import { PageHeader } from "@/components/app-shell";
import { Pill, SourceBanner } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
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
            <p className="text-muted-foreground border-t pt-3 text-xs">
              Anonymizer does not store request content, detected values or placeholders. Original and anonymized
              text are only visible to the calling application (privacy by design).
            </p>
          </CardContent></Card>
        <div className="space-y-4">
          <Card><CardHeader><CardDescription>Summary</CardDescription></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                {t.upstream && <>
                  <dt className="text-muted-foreground">Upstream</dt><dd className="font-mono">{t.upstream}</dd>
                  <dt className="text-muted-foreground">Tool</dt><dd className="font-mono break-all">{t.tool}</dd>
                  <dt className="text-muted-foreground">Mode</dt><dd><Pill value={t.mode} /></dd>
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

import { PageHeader } from "@/components/app-shell";
import { Distribution, SourceBanner, fmt, pct } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { getMetrics } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

export default async function Privacy() {
  const { data: m, source } = await getMetrics(24);
  return (
    <>
      <PageHeader title="Privacy" description={`Detections & actions · last ${m.window_hours} hours`} />
      <SourceBanner source={source} />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-3">
        <Card><CardHeader><CardDescription>Entity types</CardDescription></CardHeader>
          <CardContent><Distribution data={m.entity_distribution} empty="No detections yet" /></CardContent></Card>
        <Card><CardHeader><CardDescription>Actions applied</CardDescription></CardHeader>
          <CardContent><Distribution data={m.actions} empty="No actions yet" /></CardContent></Card>
        <Card><CardHeader><CardDescription>Risk of requests</CardDescription></CardHeader>
          <CardContent>
            <Distribution data={m.by_risk} />
            <dl className="mt-4 grid grid-cols-2 gap-2 border-t pt-3 text-xs">
              <dt className="text-muted-foreground">Detections</dt><dd className="tabular-nums">{fmt(m.detections)}</dd>
              <dt className="text-muted-foreground">Anonymization rate</dt><dd className="tabular-nums">{pct(m.anonymization_rate)}</dd>
              <dt className="text-muted-foreground">Not sent</dt><dd className="tabular-nums">{fmt(m.not_allowed)}</dd>
            </dl>
          </CardContent></Card>
        <Card className="lg:col-span-3"><CardHeader><CardDescription>Review queue</CardDescription></CardHeader>
          <CardContent className="text-muted-foreground text-xs">
            {fmt(m.by_outcome.review ?? 0)} request(s) were held for human review. An approval workflow is not
            part of this version yet; the calling application receives the outcome and decides.
          </CardContent></Card>
      </div>
    </>
  );
}

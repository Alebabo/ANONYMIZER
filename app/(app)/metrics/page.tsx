import { PageHeader } from "@/components/app-shell";
import { Bars, Distribution, SourceBanner, Stat, fmt, pct } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { getMetrics } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

export default async function Metrics() {
  const { data: m, source } = await getMetrics(24);
  return (
    <>
      <PageHeader title="Metrics" description={`Last ${m.window_hours} hours`} />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:space-y-6 md:p-6">
        <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          <Stat label="Detection rate" value={pct(m.detection_rate)} sub={`${fmt(m.requests_with_detections)} of ${fmt(m.requests)} requests`} />
          <Stat label="Anonymization rate" value={pct(m.anonymization_rate)} sub={`${fmt(m.anonymized_entities)} entities`} />
          <Stat label="Block rate" value={pct(m.block_rate)} sub={`${fmt(m.not_allowed)} not sent`} />
          <Stat label="Latency" value={m.latency_ms.avg != null ? `${m.latency_ms.avg} ms` : "–"} sub={m.latency_ms.p95 != null ? `p95 ${m.latency_ms.p95} ms` : undefined} />
        </div>
        <Card><CardHeader><CardDescription>Requests per hour</CardDescription></CardHeader>
          <CardContent><Bars series={m.timeseries} label="Requests per hour" /></CardContent></Card>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card><CardHeader><CardDescription>Outcomes</CardDescription></CardHeader><CardContent><Distribution data={m.by_outcome} /></CardContent></Card>
          <Card><CardHeader><CardDescription>Providers</CardDescription></CardHeader><CardContent><Distribution data={m.by_provider} empty="No provider traffic" /></CardContent></Card>
          <Card><CardHeader><CardDescription>Policies</CardDescription></CardHeader><CardContent><Distribution data={m.by_policy} /></CardContent></Card>
          <Card><CardHeader><CardDescription>Endpoints</CardDescription></CardHeader><CardContent><Distribution data={m.by_route} /></CardContent></Card>
        </div>
        <p className="text-muted-foreground text-xs">
          False positive / false negative rates need labelled feedback and are measured offline with
          <code className="mx-1">cato eval</code>; they are not derived from live traffic.
        </p>
      </div>
    </>
  );
}

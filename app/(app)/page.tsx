import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Bars, Distribution, Pill, SourceBanner, Stat, fmt, pct, time } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getMetrics, getTraces } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

export default async function Overview() {
  const [{ data: m, source }, { data: traces }] = await Promise.all([getMetrics(24), getTraces(8)]);
  return (
    <>
      <PageHeader title="Overview" description={`Last ${m.window_hours} hours`} />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:space-y-6 md:p-6">
        <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          <Stat label="Total requests" value={fmt(m.requests)} sub={`${fmt(m.errors)} errors`} />
          <Stat label="Requests with detections" value={fmt(m.requests_with_detections)} sub={`${pct(m.detection_rate)} of requests`} />
          <Stat label="Anonymized entities" value={fmt(m.anonymized_entities)} sub={`${pct(m.anonymization_rate)} of ${fmt(m.detections)} detections`} />
          <Stat label="Not sent" value={fmt(m.not_allowed)} sub={`review / local only / block · ${pct(m.block_rate)}`} />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2"><CardHeader><CardDescription>Request volume per hour</CardDescription></CardHeader>
            <CardContent><Bars series={m.timeseries} label="Requests per hour" /></CardContent></Card>
          <Card><CardHeader><CardDescription>Outcomes</CardDescription></CardHeader>
            <CardContent><Distribution data={m.by_outcome} /></CardContent></Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2"><CardHeader><CardDescription>Recent activity</CardDescription></CardHeader>
            <CardContent>
              <TableScroll minWidth={480}><Table><TableHeader><TableRow>
                <TableHead>Time</TableHead><TableHead>Route</TableHead><TableHead>Risk</TableHead><TableHead>Outcome</TableHead>
              </TableRow></TableHeader>
                <TableBody>{traces.map(t => (
                  <TableRow key={t.id}>
                    <TableCell>{time(t.created_at)}</TableCell>
                    <TableCell><Link className="text-link hover:text-link-hover" href={`/traces/${t.id}`}>{t.route}</Link></TableCell>
                    <TableCell><Pill value={t.risk} /></TableCell><TableCell><Pill value={t.outcome} /></TableCell>
                  </TableRow>))}
                </TableBody></Table></TableScroll>
            </CardContent></Card>
          <Card><CardHeader><CardDescription>Providers</CardDescription></CardHeader>
            <CardContent><Distribution data={m.by_provider} empty="No provider traffic yet" /></CardContent></Card>
        </div>
      </div>
    </>
  );
}

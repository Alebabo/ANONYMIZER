import { PageHeader, Badge, TableScroll } from "@/components/app-shell";
import { Card, CardContent, CardHeader, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const stats = [
  ["Total requests", "24,891", "+12.4%"],
  ["PII detections", "3,421", "13.7% of requests"],
  ["Anonymized", "2,817", "82.3% of detections"],
  ["Blocked", "104", "Policy violations"],
];
const activity = [["14:32", "PII detected", "Processed"], ["14:30", "Policy violation", "Blocked"], ["14:28", "Request processed", "Processed"]];

export default function Overview() {
  return (
    <>
      <PageHeader title="Overview" description="Last 24 hours · Example data" />
      <div className="space-y-4 p-4 md:space-y-6 md:p-6">
        <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          {stats.map(([k, v, s]) => (
            <Card key={k}><CardHeader><CardDescription>{k}</CardDescription></CardHeader>
              <CardContent><div className="text-xl font-bold md:text-2xl">{v}</div><div className="text-muted-foreground text-xs">{s}</div></CardContent></Card>
          ))}
        </div>
        <Card><CardHeader><CardDescription>Request volume</CardDescription></CardHeader>
          <CardContent><div className="bg-muted/50 text-muted-foreground flex h-32 items-center md:h-40 justify-center rounded-md text-xs">Chart placeholder · wired to /v1/metrics later</div></CardContent></Card>
        <Card><CardHeader><CardDescription>Recent activity</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={360}><Table><TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Event</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>{activity.map(([t, e, s]) => <TableRow key={t}><TableCell>{t}</TableCell><TableCell>{e}</TableCell><TableCell><Badge>{s}</Badge></TableCell></TableRow>)}</TableBody></Table></TableScroll>
          </CardContent></Card>
      </div>
    </>
  );
}

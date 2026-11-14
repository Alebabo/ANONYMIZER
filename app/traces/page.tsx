import Link from "next/link";
import { PageHeader, Badge } from "@/components/app-shell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { traces } from "@/lib/mock";

export default function Traces() {
  return (
    <>
      <PageHeader title="Traces" description="Example data" />
      <Table><TableHeader><TableRow>{["Trace", "Route", "Status", "Provider", "Entities", "Latency", "Time"].map(h => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
        <TableBody>{traces.map(t => (
          <TableRow key={t.id}><TableCell><Link className="text-link hover:text-link-hover" href={`/traces/${t.id}`}>{t.id}</Link></TableCell><TableCell>{t.route}</TableCell>
            <TableCell><Badge>{t.status}</Badge></TableCell><TableCell>{t.provider}</TableCell><TableCell>{t.entities}</TableCell><TableCell>{t.latency}</TableCell><TableCell>{t.time}</TableCell></TableRow>
        ))}</TableBody></Table>
    </>
  );
}

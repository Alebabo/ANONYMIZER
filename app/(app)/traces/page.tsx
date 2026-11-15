import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Pill, SourceBanner, time } from "@/components/dashboard";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getTraces } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

export default async function Traces() {
  const { data: traces, source } = await getTraces(100);
  return (
    <>
      <PageHeader title="Traces" description="Metadata only · no content stored" />
      <SourceBanner source={source} />
      <TableScroll minWidth={820}>
        <Table><TableHeader><TableRow>
          {["Trace", "Time", "Route", "Risk", "Outcome", "Entities", "Provider", "Latency"].map(h => <TableHead key={h}>{h}</TableHead>)}
        </TableRow></TableHeader>
          <TableBody>{traces.map(t => (
            <TableRow key={t.id}>
              <TableCell className="font-mono"><Link className="text-link hover:text-link-hover" href={`/traces/${t.id}`}>{t.id}</Link></TableCell>
              <TableCell>{time(t.created_at)}</TableCell>
              <TableCell>{t.route}</TableCell>
              <TableCell><Pill value={t.risk} /></TableCell>
              <TableCell><Pill value={t.outcome} /></TableCell>
              <TableCell className="tabular-nums">{Object.values(t.entity_counts).reduce((a, b) => a + b, 0)}</TableCell>
              <TableCell>{t.provider ? `${t.provider}${t.model ? ` · ${t.model}` : ""}` : "–"}</TableCell>
              <TableCell className="tabular-nums">{t.latency_ms != null ? `${t.latency_ms} ms` : "–"}</TableCell>
            </TableRow>))}
            {!traces.length && <TableRow><TableCell colSpan={8} className="text-muted-foreground py-6 text-center">No traces yet</TableCell></TableRow>}
          </TableBody></Table>
      </TableScroll>
    </>
  );
}

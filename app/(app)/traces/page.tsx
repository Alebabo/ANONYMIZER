import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Pill, SourceBanner, time } from "@/components/dashboard";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getTraces } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

const filters = [{ label: "All", route: undefined }, { label: "MCP proxy", route: "/mcp/proxy" },
  { label: "Gateway", route: "/v1/chat/completions" }, { label: "Protect", route: "/v1/protect" }];

export default async function Traces({ searchParams }: { searchParams: Promise<{ route?: string }> }) {
  const { route } = await searchParams;
  const { data: traces, source } = await getTraces(100, route);
  return (
    <>
      <PageHeader title="Traces" description="Metadata only · no content stored" />
      <SourceBanner source={source} />
      <div className="flex flex-wrap gap-2 border-b px-4 py-2 text-xs md:px-6">
        {filters.map(f => (
          <Link key={f.label} href={f.route ? `/traces?route=${encodeURIComponent(f.route)}` : "/traces"}
                className={f.route === route ? "bg-muted rounded-md px-2 py-1 font-medium" : "text-muted-foreground hover:text-foreground rounded-md px-2 py-1"}>
            {f.label}
          </Link>))}
      </div>
      <TableScroll minWidth={820}>
        <Table><TableHeader><TableRow>
          {["Trace", "Time", "Route", "Risk", "Outcome", "Entities", "Provider", "Latency"].map(h => <TableHead key={h}>{h}</TableHead>)}
        </TableRow></TableHeader>
          <TableBody>{traces.map(t => (
            <TableRow key={t.id}>
              <TableCell className="font-mono"><Link className="text-link hover:text-link-hover" href={`/traces/${t.id}`}>{t.id}</Link></TableCell>
              <TableCell>{time(t.created_at)}</TableCell>
              <TableCell>{t.upstream ? <span className="font-mono">{t.upstream}__{t.tool}</span> : t.route}
                {t.mode === "observe" && <> <Pill value="observe" /></>}</TableCell>
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

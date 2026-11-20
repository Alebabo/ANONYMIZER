import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Pill, SourceBanner } from "@/components/dashboard";
import { Chip, ms, stamp } from "@/components/widgets";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getTraces } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

// Filter by channel: how the model was used. CSV = playground uploads (dashboard and MCP).
const filters: { label: string; q?: { client?: string; route?: string } }[] = [
  { label: "All" }, { label: "API", q: { client: "api" } }, { label: "MCP", q: { client: "mcp" } },
  { label: "Chat", q: { client: "dashboard", route: "/v1/protect" } }, { label: "CSV", q: { route: "/v1/playground" } },
];
const CHANNEL: Record<string, string> = { api: "API", mcp: "MCP", dashboard: "Dashboard" };
const href = (q?: { client?: string; route?: string }) => (q ? `/traces?${new URLSearchParams(q)}` : "/traces");

export default async function Traces({ searchParams }: { searchParams: Promise<{ route?: string; client?: string }> }) {
  const { route, client } = await searchParams;
  const { data: traces, source } = await getTraces(100, { route, client });
  return (
    <>
      <PageHeader title="Traces" description="Every use of the model via API, MCP, Chat or CSV: who, which policy, what was found and what left OpenAnonymizer."
                  meta={<>{traces.length} latest</>} />
      <SourceBanner source={source} />
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 md:px-6">
        <div className="bg-muted inline-flex rounded-md p-0.5 text-xs" role="tablist" aria-label="Filter by channel">
          {filters.map(f => {
            const active = (f.q?.route ?? undefined) === route && (f.q?.client ?? undefined) === client;
            return (
              <Link key={f.label} role="tab" aria-selected={active} href={href(f.q)}
                    className={cn("rounded-sm px-2.5 py-1", active ? "bg-background text-foreground font-medium shadow-xs" : "text-muted-foreground hover:text-foreground")}>
                {f.label}
              </Link>);
          })}
        </div>
      </div>
      <TableScroll minWidth={1080}>
        <Table>
          <TableHeader><TableRow>
            <TableHead className="w-36">Timestamp</TableHead><TableHead className="w-56">Name</TableHead>
            <TableHead className="w-40">Channel</TableHead>
            <TableHead className="w-24">Outcome</TableHead><TableHead className="w-24">Risk</TableHead>
            <TableHead className="w-64">Personal data</TableHead><TableHead className="w-40">Policy</TableHead>
            <TableHead className="w-20 text-right">Latency</TableHead><TableHead className="w-32">ID</TableHead>
          </TableRow></TableHeader>
          <TableBody>{traces.map(t => (
            <TableRow key={t.id} className="h-9">
              <TableCell className="tabular-nums">{stamp(t.created_at)}</TableCell>
              <TableCell className="truncate">
                <Link className="text-link hover:text-link-hover font-mono" href={`/traces/${t.id}`}>
                  {t.upstream ? `${t.upstream}__${t.tool}` : t.tool ? `mcp · ${t.tool}`
                    : t.client === "dashboard" && t.route === "/v1/protect" ? "chat" : t.route}
                </Link>
                {t.resource && <span className="text-muted-foreground font-mono"> · {t.resource}</span>}
                {(t.mode === "observe" || t.mode === "log") && <> <Pill value={t.mode} /></>}
              </TableCell>
              <TableCell className="truncate" title={t.actor ?? undefined}>
                {t.client ? CHANNEL[t.client] ?? t.client : "–"}
                {t.actor && <span className="text-muted-foreground"> · {t.actor}</span>}
              </TableCell>
              <TableCell><Pill value={t.status >= 500 ? "error" : t.outcome} /></TableCell>
              <TableCell><Pill value={t.risk} /></TableCell>
              <TableCell>
                <span className="flex gap-1 overflow-hidden">
                  {Object.entries(t.entity_counts).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, n]) => <Chip key={k}>{k} {n}</Chip>)}
                  {!Object.keys(t.entity_counts).length && <span className="text-muted-foreground">–</span>}
                </span>
              </TableCell>
              <TableCell className="text-muted-foreground truncate">{t.policy ?? "–"}</TableCell>
              <TableCell className="text-right tabular-nums">{ms(t.latency_ms)}</TableCell>
              <TableCell className="text-muted-foreground truncate font-mono">{t.id}</TableCell>
            </TableRow>))}
            {!traces.length && <TableRow><TableCell colSpan={9} className="text-muted-foreground py-6 text-center">No traces yet</TableCell></TableRow>}
          </TableBody>
        </Table>
      </TableScroll>
    </>
  );
}

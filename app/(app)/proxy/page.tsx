import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Distribution, Pill, SourceBanner, Stat, fmt, time } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getProxy, getTraces, type Trace } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

type ToolRow = { key: string; upstream: string; tool: string; calls: number; withheld: number; entities: Record<string, number>; last: number };
type FieldRow = { key: string; upstream: string; tool: string; path: string; entities: Record<string, number> };

function add(into: Record<string, number>, from: Record<string, number>) {
  for (const [k, v] of Object.entries(from)) into[k] = (into[k] ?? 0) + v;
}

function aggregate(traces: Trace[]) {
  const tools = new Map<string, ToolRow>();
  const fields = new Map<string, FieldRow>();
  const entities: Record<string, number> = {};
  for (const t of traces) {
    const upstream = t.upstream ?? "?", tool = t.tool ?? "?", key = `${upstream}__${tool}`;
    const row = tools.get(key) ?? { key, upstream, tool, calls: 0, withheld: 0, entities: {}, last: 0 };
    row.calls += 1;
    if (t.outcome && t.outcome !== "allow") row.withheld += 1;
    row.last = Math.max(row.last, t.created_at);
    add(row.entities, t.entity_counts);
    tools.set(key, row);
    add(entities, t.entity_counts);
    for (const [path, counts] of Object.entries(t.fields ?? {})) {
      const fk = `${key} ${path}`;
      const f = fields.get(fk) ?? { key: fk, upstream, tool, path, entities: {} };
      add(f.entities, counts);
      fields.set(fk, f);
    }
  }
  const total = (r: Record<string, number>) => Object.values(r).reduce((a, b) => a + b, 0);
  return {
    tools: [...tools.values()].sort((a, b) => b.last - a.last),
    fields: [...fields.values()].sort((a, b) => total(b.entities) - total(a.entities)),
    entities,
  };
}

const list = (r: Record<string, number>) =>
  Object.entries(r).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(" · ") || "–";

export default async function Proxy() {
  const [{ data: status, source }, { data: traces }] = await Promise.all([getProxy(), getTraces(500, "/mcp/proxy")]);
  const agg = aggregate(traces);
  const observe = status?.upstreams.filter(u => u.mode === "observe") ?? [];
  return (
    <>
      <PageHeader title="MCP Proxy" description="Other MCP servers behind Cato · metadata only, no values stored" />
      <SourceBanner source={source} />
      {observe.length > 0 && (
        <div className="bg-light-yellow text-dark-yellow border-b px-4 py-2 text-xs md:px-6">
          Observe mode for {observe.map(u => u.name).join(", ")}: results reach the model unfiltered. Use only with test data or after approval.
        </div>
      )}
      <div className="grid min-w-0 grid-cols-1 gap-4 p-4 md:p-6 [&>*]:min-w-0">
        <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          <Stat label="Tool calls" value={fmt(traces.length)} sub="last 500" />
          <Stat label="Entities found" value={fmt(Object.values(agg.entities).reduce((a, b) => a + b, 0))} />
          <Stat label="Calls with withheld data" value={fmt(agg.tools.reduce((a, t) => a + t.withheld, 0))} />
          <Stat label="Upstreams" value={status ? `${status.upstreams.filter(u => u.connected).length}/${status.upstreams.length}` : "–"}
                sub={status ? "connected (this API)" : "stdio proxy: see traces"} />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 [&>*]:min-w-0">
          <Card className="lg:col-span-2"><CardHeader><CardDescription>Upstreams</CardDescription></CardHeader>
            <CardContent>
              {status ? (
                <TableScroll minWidth={560}>
                  <Table><TableHeader><TableRow>
                    {["Name", "Transport", "Mode", "Policy", "Status", "Tools"].map(h => <TableHead key={h}>{h}</TableHead>)}
                  </TableRow></TableHeader>
                    <TableBody>{status.upstreams.map(u => (
                      <TableRow key={u.name}>
                        <TableCell className="font-mono">{u.name}</TableCell>
                        <TableCell>{u.transport}</TableCell>
                        <TableCell><Pill value={u.mode} /></TableCell>
                        <TableCell>{u.policy}</TableCell>
                        <TableCell><Pill value={u.connected ? "connected" : "disconnected"} />{u.error ? ` ${u.error}` : ""}</TableCell>
                        <TableCell className="tabular-nums">{u.tools_exposed} / {u.tools_upstream}</TableCell>
                      </TableRow>))}
                    </TableBody></Table>
                </TableScroll>
              ) : (
                <p className="text-muted-foreground text-xs">
                  The API does not run a proxy (CATO_PROXY_CONFIG not set). Calls from a stdio proxy
                  (<code>cato-proxy --config …</code>) still appear below if it writes to the same trace database.
                </p>
              )}
            </CardContent></Card>
          <Card><CardHeader><CardDescription>Entity types found</CardDescription></CardHeader>
            <CardContent><Distribution data={agg.entities} empty="No proxy calls yet" /></CardContent></Card>
        </div>

        <Card><CardHeader><CardDescription>Per tool</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={720}>
              <Table><TableHeader><TableRow>
                {["Upstream", "Tool", "Calls", "Withheld", "Entities", "Last call"].map(h => <TableHead key={h}>{h}</TableHead>)}
              </TableRow></TableHeader>
                <TableBody>{agg.tools.map(r => (
                  <TableRow key={r.key}>
                    <TableCell className="font-mono">{r.upstream}</TableCell>
                    <TableCell className="font-mono">{r.tool}</TableCell>
                    <TableCell className="tabular-nums">{fmt(r.calls)}</TableCell>
                    <TableCell className="tabular-nums">{fmt(r.withheld)}</TableCell>
                    <TableCell className="text-xs">{list(r.entities)}</TableCell>
                    <TableCell>{time(r.last)}</TableCell>
                  </TableRow>))}
                  {!agg.tools.length && <TableRow><TableCell colSpan={6} className="text-muted-foreground py-6 text-center">No proxy calls yet</TableCell></TableRow>}
                </TableBody></Table>
            </TableScroll>
          </CardContent></Card>

        <Card><CardHeader><CardDescription>Where personal data was found (field paths, array indices collapsed)</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={720}>
              <Table><TableHeader><TableRow>
                {["Tool", "Field", "Entity types"].map(h => <TableHead key={h}>{h}</TableHead>)}
              </TableRow></TableHeader>
                <TableBody>{agg.fields.map(f => (
                  <TableRow key={f.key}>
                    <TableCell className="font-mono">{f.upstream}__{f.tool}</TableCell>
                    <TableCell className="font-mono break-all">{f.path}</TableCell>
                    <TableCell className="text-xs">{list(f.entities)}</TableCell>
                  </TableRow>))}
                  {!agg.fields.length && <TableRow><TableCell colSpan={3} className="text-muted-foreground py-6 text-center">No entities found yet</TableCell></TableRow>}
                </TableBody></Table>
            </TableScroll>
            <p className="text-muted-foreground mt-3 text-xs">
              Cato stores types, counts and field paths only. Values, placeholders and results are never stored.
              Single calls: <Link className="text-link hover:text-link-hover" href="/traces?route=/mcp/proxy">traces of the proxy</Link>.
            </p>
          </CardContent></Card>
      </div>
    </>
  );
}

import Link from "next/link";
import { Play } from "lucide-react";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { SourceBanner, ago, fmt } from "@/components/dashboard";
import { Chip, Widget, stamp } from "@/components/widgets";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getDatasets, queryDataset, type Dataset, type PlaygroundResult } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";
import { InlineDiff } from "@/components/inline-diff";
import { Process } from "./process";
import { DeleteDataset, UploadForm } from "./upload-form";

export const dynamic = "force-dynamic";

type Params = { ds?: string; q?: string; limit?: string; offset?: string; view?: string };
const VIEWS = [
  { key: "compare", label: "Compare" },
  { key: "claude", label: "What Claude gets" },
  { key: "json", label: "Raw JSON" },
] as const;

const cell = (v: unknown) => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v));

export default async function Playground({ searchParams }: { searchParams: Promise<Params> }) {
  const p = await searchParams;
  const { data: datasets, source } = await getDatasets();
  const active = datasets.find(d => d.id === p.ds) ?? null;
  const limit = Math.min(100, Math.max(1, Number(p.limit) || 20));
  const offset = Math.max(0, Number(p.offset) || 0);
  const view = VIEWS.find(v => v.key === p.view)?.key ?? "compare";
  const result = active ? (await queryDataset(active.id, { query: p.q, limit, offset })).data : null;
  const link = (over: Partial<Params>) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries({ ds: active?.id, q: p.q, limit: String(limit), view, ...over }))
      if (v) sp.set(k, String(v));
    return `/playground?${sp}`;
  };

  return (
    <>
      <PageHeader title="Playground"
                  description="Upload a CSV, query it and see exactly what Claude receives. Uses the same protection as the MCP proxy; column names count as hints (vorname, email, iban …)."
                  meta={<span className="bg-light-yellow text-dark-yellow rounded-md px-1.5 py-0.5">Test data only</span>} />
      <SourceBanner source={source} />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[280px_1fr]">
        <div className="space-y-4">
          <Widget title="Uploads" description="Click a file to see how it was anonymized">
            <ul className="mb-3 space-y-1">
              {[...datasets].sort((a, b) => b.created_at - a.created_at).map(d => (
                <li key={d.id}>
                  <Link href={`/playground?ds=${d.id}`} aria-current={d.id === active?.id ? "page" : undefined}
                        className={cn("block rounded-md border px-2 py-1.5 text-xs",
                          d.id === active?.id ? "bg-muted border-border-contrast font-medium" : "hover:bg-muted/50 border-transparent")}>
                    <div className="truncate" title={d.name}>{d.name}</div>
                    <div className="text-muted-foreground text-2xs">{ago(d.created_at)} · {fmt(d.rows)} rows · {d.columns.length} cols</div>
                  </Link>
                </li>
              ))}
              {!datasets.length && <li className="text-muted-foreground py-2 text-xs">Nothing uploaded yet</li>}
            </ul>
            <UploadForm />
          </Widget>
          {active && (
            <Widget title="Ask Claude" description="Claude reads the same data through MCP">
              <p className="text-muted-foreground mb-2 text-xs">In Claude Code (MCP server <code>anonymizer</code> connected), e.g.:</p>
              <pre className="bg-surface-code rounded-md p-2 text-2xs whitespace-pre-wrap">
{`Nutze anonymizer query_dataset mit dataset_id "${active.id}" und sag mir, welche Anliegen am häufigsten sind.`}</pre>
              <p className="text-muted-foreground mt-2 text-2xs">Each call shows up under <Link className="text-link" href="/traces?route=%2Fv1%2Fplayground">Traces</Link> with input and output.</p>
            </Widget>
          )}
        </div>

        <div className="min-w-0 space-y-4">
          {!active && (
            <div className="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
              Upload a CSV or pick an upload on the left to see its anonymization step by step.
            </div>
          )}
          {active && (
            <>
              <form method="get" action="/playground" className="bg-card flex flex-wrap items-center gap-2 rounded-lg border p-2">
                <input type="hidden" name="ds" value={active.id} />
                <input type="hidden" name="view" value={view} />
                <Input name="q" defaultValue={p.q ?? ""} placeholder={`Search ${active.name} (all columns)`} className="h-8 min-w-48 flex-1" />
                <select name="limit" defaultValue={String(limit)} aria-label="Rows"
                        className="border-input bg-background h-8 rounded-md border px-2 text-sm">
                  {[10, 20, 50, 100].map(n => <option key={n} value={n}>{n} rows</option>)}
                </select>
                <button type="submit" className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm">
                  <Play className="h-3.5 w-3.5" />Run
                </button>
              </form>
              {result ? <Result ds={active} r={result} view={view} link={link} offset={offset} limit={limit} /> : (
                <p className="text-muted-foreground text-xs">Dataset not found.</p>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

function Result({ ds, r, view, link, offset, limit }: {
  ds: Dataset; r: PlaygroundResult; view: string; link: (o: Partial<Params>) => string; offset: number; limit: number;
}) {
  const sent = Array.isArray(r.rows) ? r.rows : null;
  const orig = r.original ?? [];
  const titles = new Map((r.replacements ?? []).filter(x => x.replacement).map(x => [x.replacement!, `${x.type} · ${x.method ?? "–"}`]));
  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Chip label="Matched">{fmt(r.matched)} of {fmt(r.dataset.rows)}</Chip>
        <Chip label="Shown">{r.matched ? `${offset + 1}–${Math.min(offset + limit, r.matched)}` : "0"}</Chip>
        {Object.entries(r.entities ?? {}).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).map(([k, n]) => <Chip key={k}>{k} {n}</Chip>)}
        {!!r.withheld && <Chip className="bg-light-red text-dark-red">{r.withheld} withheld</Chip>}
        <Link href={`/traces/${r.trace_id}`} className="text-link hover:text-link-hover ml-auto">Trace {r.trace_id} →</Link>
        <DeleteDataset id={ds.id} />
      </div>

      <Process ds={ds} r={r} />

      <div className="bg-muted inline-flex rounded-md p-0.5 text-xs" role="tablist">
        {VIEWS.map(v => (
          <Link key={v.key} role="tab" aria-selected={v.key === view} href={link({ view: v.key, offset: String(offset) })}
                className={cn("rounded-sm px-2.5 py-1", v.key === view ? "bg-background text-foreground font-medium shadow-xs" : "text-muted-foreground hover:text-foreground")}>
            {v.label}
          </Link>
        ))}
      </div>

      {view === "json" || !sent ? (
        <pre className="bg-surface-code max-h-[32rem] overflow-auto rounded-lg p-3 font-mono text-xs whitespace-pre-wrap">{r.sent ?? cell(r.rows)}</pre>
      ) : (
        <div className="rounded-lg border">
          <TableScroll minWidth={Math.max(640, r.columns.length * 160)}>
            <Table>
              <TableHeader><TableRow>
                <TableHead className="w-10">#</TableHead>
                {r.columns.map(c => <TableHead key={c} className="font-mono">{c}</TableHead>)}
              </TableRow></TableHeader>
              <TableBody>
                {sent.map((row, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-muted-foreground align-top tabular-nums">{offset + i + 1}</TableCell>
                    {r.columns.map(c => {
                      const after = cell(row[c]);
                      const before = orig[i]?.[c] ?? "";
                      const changed = view === "compare" && orig.length > 0 && before !== after;
                      return (
                        <TableCell key={c} className="py-1.5 align-top leading-6 break-words">
                          {changed ? <InlineDiff before={before} after={after} titles={titles} /> : <span>{after}</span>}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
                {!sent.length && <TableRow><TableCell colSpan={r.columns.length + 1} className="text-muted-foreground py-6 text-center">No matching rows</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableScroll>
        </div>
      )}

      {r.matched > limit && (
        <div className="flex justify-end gap-2 text-xs">
          {offset > 0 && <Link className="text-link" href={link({ offset: String(Math.max(0, offset - limit)) })}>← Previous</Link>}
          {offset + limit < r.matched && <Link className="text-link" href={link({ offset: String(offset + limit) })}>Next →</Link>}
        </div>
      )}

      {!!r.replacements?.length && (
        <Widget title="Replacements" description="Original value and what Claude got instead (this page only, never sent to Claude)">
          <TableScroll minWidth={560}>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Original</TableHead><TableHead>Claude gets</TableHead><TableHead className="w-28">Type</TableHead>
                <TableHead>Field</TableHead><TableHead className="w-28">Method</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {r.replacements.map((x, i) => (
                  <TableRow key={i} className="h-8">
                    <TableCell className="font-mono break-all">{x.original}</TableCell>
                    <TableCell className="font-mono break-all">{x.replacement ?? "[WITHHELD]"}</TableCell>
                    <TableCell>{x.type}</TableCell>
                    <TableCell className="text-muted-foreground font-mono">{x.field ?? "–"}</TableCell>
                    <TableCell>{x.method ?? "–"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableScroll>
        </Widget>
      )}
      <p className="text-muted-foreground text-2xs">Queried {stamp(Date.now() / 1000)} · every query is traced and audited.</p>
    </>
  );
}

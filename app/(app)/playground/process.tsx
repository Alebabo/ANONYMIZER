import { ArrowRight } from "lucide-react";
import { TableScroll } from "@/components/app-shell";
import { ago, chars, fmt } from "@/components/dashboard";
import { Chip } from "@/components/widgets";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Dataset, PlaygroundResult } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

type Replacement = NonNullable<PlaygroundResult["replacements"]>[number];

/** "$[].vorname" or "$[3].vorname" -> "vorname"; anything else stays as is. */
const column = (field: string | null) => (field ?? "").replace(/^\$\[\d*\]\.?/, "") || "–";

function count<T>(items: T[], key: (t: T) => string) {
  const out: Record<string, number> = {};
  for (const i of items) out[key(i)] = (out[key(i)] ?? 0) + 1;
  return out;
}

const text = (v: unknown) => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v));

const chips = (r: Record<string, number>) =>
  Object.entries(r).sort((a, b) => b[1] - a[1]).map(([k, n]) => <Chip key={k}>{k} {n}</Chip>);

function Step({ n, title, children, tone }: { n: number; title: string; children: React.ReactNode; tone?: "warn" }) {
  return (
    <li className="bg-card min-w-0 flex-1 rounded-lg border p-3">
      <div className="flex items-center gap-2 text-xs font-medium">
        <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs",
          tone === "warn" ? "bg-light-red text-dark-red" : "bg-muted")}>{n}</span>
        {title}
      </div>
      <div className="mt-2 space-y-1.5 text-xs">{children}</div>
    </li>
  );
}

const Arrow = () => <ArrowRight aria-hidden className="text-muted-foreground hidden h-4 w-4 shrink-0 self-center lg:block" />;

/**
 * The anonymization of one upload, step by step: what came in, what was found per column, what was done
 * with it and what Claude finally receives. Built from the dashboard query result (originals included).
 */
export function Process({ ds, r }: { ds: Dataset; r: PlaygroundResult }) {
  const reps: Replacement[] = r.replacements ?? [];
  const byColumn = new Map<string, Replacement[]>();
  for (const x of reps) byColumn.set(column(x.field), [...(byColumn.get(column(x.field)) ?? []), x]);
  // Count changed cells by comparing original and output: a value replaced once (e.g. a surname) is listed
  // only once in `replacements`, but also changes free-text columns that mention it.
  const sentRows = Array.isArray(r.rows) ? r.rows : [];
  const orig = r.original ?? [];
  const changed = Object.fromEntries(r.columns.map(c => [c, sentRows.filter((row, i) => text(row[c]) !== (orig[i]?.[c] ?? "")).length]));
  const touched = r.columns.filter(c => changed[c]);
  const methods = count(reps, x => (x.replacement == null ? "withheld" : x.method ?? "replaced"));
  const sentChars = r.sent?.length ?? (typeof r.rows === "string" ? r.rows.length : JSON.stringify(r.rows).length);
  const shown = sentRows.length;

  return (
    <div className="space-y-4">
      <ol className="flex flex-col gap-2 lg:flex-row">
        <Step n={1} title="Uploaded">
          <div className="truncate font-medium" title={ds.name}>{ds.name}</div>
          <div className="text-muted-foreground">{fmt(ds.rows)} rows · {ds.columns.length} columns</div>
          <div className="text-muted-foreground">{ago(ds.created_at)}{ds.created_by ? ` · ${ds.created_by}` : ""}</div>
        </Step>
        <Arrow />
        <Step n={2} title="Detected">
          <div><b className="tabular-nums">{fmt(reps.length)}</b> distinct personal values in {touched.length} of {r.columns.length} columns</div>
          <div className="flex flex-wrap gap-1">{chips(r.entities ?? count(reps, x => x.type))}</div>
          {!reps.length && <div className="text-muted-foreground">Nothing personal found in these rows</div>}
        </Step>
        <Arrow />
        <Step n={3} title="Protected" tone={r.withheld ? "warn" : undefined}>
          <div className="flex flex-wrap gap-1">{chips(methods)}</div>
          <div className="text-muted-foreground">Placeholders stay consistent: same value, same placeholder</div>
          {!!r.withheld && <div className="text-dark-red">{fmt(r.withheld)} value(s) withheld by the policy</div>}
        </Step>
        <Arrow />
        <Step n={4} title="Sent to Claude">
          <div><b className="tabular-nums">{fmt(shown)}</b> rows · {chars(sentChars)} chars</div>
          <div className="text-muted-foreground">Only placeholders. Originals stay in OpenAnonymizer</div>
        </Step>
      </ol>

      <div>
        <h3 className="mb-1 text-xs font-medium">Per column <span className="text-muted-foreground font-normal">(rows on this page)</span></h3>
        <TableScroll minWidth={640}>
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-40">Column</TableHead><TableHead className="w-32">Result</TableHead>
              <TableHead>Found</TableHead><TableHead>Example</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {r.columns.map(c => {
                const xs = byColumn.get(c) ?? [];
                const ex = xs[0];
                const n = changed[c] ?? 0;
                return (
                  <TableRow key={c} className="h-9">
                    <TableCell className="font-mono">{c}</TableCell>
                    <TableCell>
                      {n ? <Chip className="bg-light-green text-dark-green">{fmt(n)} of {fmt(shown)} changed</Chip>
                        : <span className="text-muted-foreground">unchanged</span>}
                    </TableCell>
                    <TableCell><span className="flex flex-wrap gap-1">{xs.length ? chips(count(xs, x => x.type)) : n ? <span className="text-muted-foreground">values from other columns</span> : "–"}</span></TableCell>
                    <TableCell className="font-mono text-xs break-all">
                      {ex ? <>
                        <span className="bg-light-red text-dark-red rounded-sm px-1">{ex.original}</span>
                        <ArrowRight aria-label="becomes" className="text-muted-foreground mx-1 inline h-3 w-3" />
                        <span className="bg-light-green text-dark-green rounded-sm px-1">{ex.replacement ?? "[WITHHELD]"}</span>
                      </> : <span className="text-muted-foreground">–</span>}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableScroll>
      </div>
    </div>
  );
}

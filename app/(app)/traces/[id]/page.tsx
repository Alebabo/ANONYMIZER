import { notFound } from "next/navigation";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Pill, SourceBanner } from "@/components/dashboard";
import { Chip, Dot, ms, stamp, type DotState } from "@/components/widgets";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getTrace } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

// Step kinds borrow the Langfuse observation hues so the tree reads like a Langfuse trace.
const kind = (name: string): { tag: string; color: string } => {
  const n = name.toLowerCase();
  if (n.includes("detection") || n.includes("classification")) return { tag: "GUARD", color: "var(--observation-guardrail-fill)" };
  if (n.includes("policy") || n.includes("observe")) return { tag: "EVAL", color: "var(--observation-evaluator-fill)" };
  if (n.includes("anonymi") || n.includes("restore")) return { tag: "SPAN", color: "var(--observation-span-fill)" };
  if (n.includes("tool") || n.includes("upstream")) return { tag: "TOOL", color: "var(--observation-tool-fill)" };
  if (n.includes("provider")) return { tag: "GEN", color: "var(--observation-generation-fill)" };
  return { tag: "EVENT", color: "var(--observation-event-fill)" };
};
const stepState = (s: string): DotState => (s === "ok" ? "ok" : s === "warning" ? "warn" : "error");

function Section({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border", className)}>
      <h2 className="bg-surface-section border-b px-3 py-1.5 text-xs font-medium">{title}</h2>
      <div className="p-3">{children}</div>
    </section>
  );
}

export default async function TraceDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { data: t, source } = await getTrace(id);
  if (!t) notFound();
  const entities = Object.values(t.entity_counts).reduce((a, b) => a + b, 0);
  const name = t.upstream ? `${t.upstream}__${t.tool}` : t.route;
  const meta: [string, React.ReactNode][] = [
    ...(t.upstream ? [["Upstream", <span key="u" className="font-mono">{t.upstream}</span>], ["Tool", <span key="t" className="font-mono">{t.tool}</span>],
      ["Mode", <Pill key="m" value={t.mode} />]] as [string, React.ReactNode][] : []),
    ...(t.resource ? [["Resource", <span key="r" className="font-mono break-all">{t.resource}</span>]] as [string, React.ReactNode][] : []),
    ["Route", <span key="ro" className="font-mono">{t.route}</span>],
    ["Policy", t.policy ?? "–"],
    ["Policy hash", <span key="h" className="font-mono break-all">{t.policy_hash?.slice(0, 23) ?? "–"}</span>],
    ["Destination", t.destination ?? "–"],
    ["Provider", t.provider ? `${t.provider}${t.model ? ` · ${t.model}` : ""}` : "–"],
    ["Language", t.language ?? "–"],
    ["HTTP status", `${t.status}${t.error ? ` · ${t.error}` : ""}`],
    ["Needs review", t.needs_review ? "yes" : "no"],
    ["Signals", t.signals.join(", ") || "–"],
  ];

  return (
    <>
      <PageHeader title="Trace" parent={{ label: "Traces", href: "/traces" }}
                  meta={<span className="bg-muted rounded-md px-1.5 py-0.5 font-mono">{t.id}</span>}>
        <Pill value={t.status >= 500 ? "error" : t.outcome} />
      </PageHeader>
      <SourceBanner source={source} />
      <div className="flex flex-wrap gap-1.5 border-b px-4 py-2 md:px-6">
        <Chip>{stamp(t.created_at)}</Chip>
        <Chip label="Latency">{ms(t.latency_ms)}</Chip>
        <Chip label="Risk">{t.risk ?? "–"}</Chip>
        <Chip label="Entities">{entities}</Chip>
        <Chip label="Replaced">{t.transformations}</Chip>
        {t.policy && <Chip label="Policy">{t.policy}</Chip>}
        {t.resource && <Chip label="Resource"><span className="font-mono">{t.resource}</span></Chip>}
      </div>

      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[minmax(260px,340px)_1fr]">
        {/* Observation tree */}
        <div className="h-fit rounded-lg border">
          <div className="bg-surface-section border-b px-3 py-1.5 text-xs font-medium">Steps</div>
          <ol className="p-2 text-xs">
            <li className="flex items-center gap-2 rounded-md px-1.5 py-1">
              <span className="rounded-sm px-1 text-2xs font-medium text-white" style={{ background: "var(--observation-trace-fill)" }}>TRACE</span>
              <span className="min-w-0 flex-1 truncate font-mono font-medium" title={name}>{name}</span>
              <span className="text-muted-foreground tabular-nums">{ms(t.latency_ms)}</span>
            </li>
            {t.steps.map((s, i) => {
              const k = kind(s.name);
              return (
                <li key={i} className="relative ml-3 border-l pl-3">
                  <span className="absolute top-3 left-0 w-2.5 border-t" aria-hidden />
                  <div className="hover:bg-muted/50 rounded-md px-1.5 py-1">
                    <div className="flex items-center gap-2">
                      <span className="w-12 shrink-0 rounded-sm px-1 text-center text-2xs font-medium text-white" style={{ background: k.color }}>{k.tag}</span>
                      <span className="min-w-0 flex-1 truncate font-medium">{s.name}</span>
                      <Dot state={stepState(s.status)} />
                    </div>
                    <div className="text-muted-foreground mt-0.5 pl-14">{s.detail}</div>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>

        <div className="min-w-0 space-y-4">
          {t.warnings.length > 0 && (
            <div className="bg-light-yellow text-dark-yellow rounded-md px-3 py-2 text-xs">{t.warnings.join(" · ")}</div>
          )}

          {t.content?.length ? (
            <Section title="Output (what left Anonymizer)">
              <p className="text-dark-yellow mb-3 text-xs">
                Content trace: shows original values in clear text. Test data only (ANONYMIZER_TRACE_CONTENT=1).
              </p>
              <div className="space-y-4">
                {t.content.map((c, i) => (
                  <div key={i} className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-mono break-all">{c.label ?? `#${i + 1}`}</span>
                      {c.withheld && <Pill value="withheld" />}
                    </div>
                    <pre className="bg-surface-code max-h-72 overflow-auto rounded-md p-3 font-mono text-xs whitespace-pre-wrap break-words">
                      {c.output ?? "– not sent (withheld by policy) –"}</pre>
                    {c.replacements.length > 0 && (
                      <TableScroll minWidth={420}><Table><TableHeader><TableRow>
                        <TableHead>Type</TableHead><TableHead>Original</TableHead><TableHead>Sent as</TableHead><TableHead>Method</TableHead>
                      </TableRow></TableHeader>
                        <TableBody>{c.replacements.map((r, j) => (
                          <TableRow key={j} className="h-8">
                            <TableCell>{r.type}</TableCell>
                            <TableCell className="font-mono break-all">{r.original}</TableCell>
                            <TableCell className="font-mono break-all">{r.replacement ?? "withheld"}</TableCell>
                            <TableCell>{r.method ?? "–"}</TableCell>
                          </TableRow>))}
                        </TableBody></Table></TableScroll>)}
                  </div>))}
              </div>
            </Section>
          ) : (
            <Section title="Output">
              <p className="text-muted-foreground text-xs">
                No content stored for this trace. Content traces are off by default; with ANONYMIZER_TRACE_CONTENT=1
                admins see what went through and which values were replaced.
              </p>
            </Section>
          )}

          <div className="grid gap-4 xl:grid-cols-2">
            <Section title="Entities & actions">
              <ul className="space-y-1 text-xs">
                {Object.entries(t.actions).sort((a, b) => b[1] - a[1]).map(([k, n]) => {
                  const [type, action] = k.split(":");
                  return (
                    <li key={k} className="flex items-center justify-between gap-2">
                      <span>{type}</span><span className="text-muted-foreground tabular-nums">{n} × <Pill value={action} /></span>
                    </li>);
                })}
                {!Object.keys(t.actions).length && <li className="text-muted-foreground">No entities</li>}
              </ul>
            </Section>
            {t.fields && Object.keys(t.fields).length > 0 ? (
              <Section title="Fields with personal data">
                <ul className="space-y-1.5 text-xs">
                  {Object.entries(t.fields).map(([path, counts]) => (
                    <li key={path} className="flex justify-between gap-3">
                      <span className="font-mono break-all">{path}</span>
                      <span className="text-muted-foreground shrink-0">{Object.entries(counts).map(([k, n]) => `${k} ${n}`).join(" · ")}</span>
                    </li>))}
                </ul>
              </Section>
            ) : <div className="hidden xl:block" />}
          </div>

          <Section title="Metadata">
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-xs">
              {meta.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{k}</dt><dd className="min-w-0">{v}</dd>
                </div>
              ))}
            </dl>
          </Section>
        </div>
      </div>
    </>
  );
}

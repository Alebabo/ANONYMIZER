import { notFound } from "next/navigation";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Notice, Pill, SourceBanner, dateTime } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PromoteForm } from "@/app/(app)/prompts/[name]/promote-form";
import { getMe, getPrompt, getPromptDiff, getPromptHistory, type PromptVersion } from "@/lib/cato-api";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

function render(p: PromptVersion["prompt"]): string {
  if (p == null) return "(not shown: the policy does not allow it)";
  if (typeof p === "string") return p;
  return p.map(m => `[${m.role}]\n${m.content ?? "(withheld)"}`).join("\n\n");
}

export default async function PromptDetail({ params, searchParams }: {
  params: Promise<{ name: string }>; searchParams: Promise<{ v?: string }>;
}) {
  const { name: raw } = await params;
  const name = decodeURIComponent(raw);
  const { v } = await searchParams;
  const version = v && /^\d+$/.test(v) ? Number(v) : undefined;
  const [{ data: current, source }, { data: history }, { data: me }] = await Promise.all([
    getPrompt(name, version), getPromptHistory(name), getMe()]);
  if (!current || !history) notFound();
  const previous = history.find(h => h.version < current.version);
  const diff = previous ? (await getPromptDiff(name, previous.version, current.version)).data : null;
  const admin = me.role === "admin" && source.live;
  return (
    <>
      <PageHeader title={name} description={`v${current.version} · ${current.type} · ${current.note ?? "no note"}`}>
        <span className="space-x-1">{current.labels.map(l => <Pill key={l} value={l} />)}</span>
      </PageHeader>
      <SourceBanner source={source} />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card><CardHeader><CardDescription>Version {current.version}{current.protected ? " (shown anonymized)" : ""}</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {current.notice && <Notice>{current.notice}</Notice>}
              {current.warnings?.map(w => <Notice key={w}>{w}</Notice>)}
              <pre className="bg-surface-code overflow-auto whitespace-pre-wrap rounded-md p-4 font-mono text-xs">{render(current.prompt)}</pre>
              {Object.keys(current.config).length > 0 &&
                <pre className="bg-surface-code overflow-auto rounded-md p-3 font-mono text-xs">{JSON.stringify(current.config, null, 2)}</pre>}
            </CardContent></Card>
          {diff && (
            <Card><CardHeader><CardDescription>Changes from v{diff.from}{diff.config_changed ? " · config changed" : ""}</CardDescription></CardHeader>
              <CardContent>
                <pre className="bg-surface-code overflow-auto rounded-md p-4 font-mono text-xs">
                  {diff.diff.split("\n").map((line, i) => (
                    <div key={i} className={cn(line.startsWith("+") && !line.startsWith("+++") && "text-dark-green",
                      line.startsWith("-") && !line.startsWith("---") && "text-dark-red")}>{line || " "}</div>))}
                </pre>
              </CardContent></Card>
          )}
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardDescription>Promote</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {!admin && <Notice>{source.live ? "Only admins can move labels." : "Demo mode: changes are disabled."}</Notice>}
              <PromoteForm name={name} version={current.version} disabled={!admin} />
              <p className="text-muted-foreground text-2xs">Moving a label is recorded in the audit log with the previous version.
                Agents cannot do this over MCP.</p>
            </CardContent></Card>
          <Card><CardHeader><CardDescription>History</CardDescription></CardHeader>
            <CardContent>
              <TableScroll minWidth={300}><Table><TableHeader><TableRow>
                <TableHead>Version</TableHead><TableHead>Labels</TableHead><TableHead>By</TableHead>
              </TableRow></TableHeader>
                <TableBody>{history.map(h => (
                  <TableRow key={h.version} className={h.version === current.version ? "bg-muted/50" : undefined}>
                    <TableCell><a className="underline-offset-2 hover:underline" href={`?v=${h.version}`}>v{h.version}</a>
                      <div className="text-muted-foreground text-2xs">{dateTime(h.created_at)}</div></TableCell>
                    <TableCell className="space-x-1">{h.labels.filter(l => l !== "latest").map(l => <Pill key={l} value={l} />)}</TableCell>
                    <TableCell className="max-w-32 truncate text-xs" title={h.note ?? ""}>{h.created_by ?? "–"}</TableCell>
                  </TableRow>))}
                </TableBody></Table></TableScroll>
            </CardContent></Card>
        </div>
      </div>
    </>
  );
}

import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Notice, Pill, SourceBanner, ago } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getPrompts, getSources } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

export default async function Prompts() {
  const [{ data: prompts, source }, { data: sources }] = await Promise.all([getPrompts(), getSources()]);
  if (!prompts || !sources.prompts) {
    return (
      <>
        <PageHeader title="Prompts" description="Versions, labels and promotion" />
        <div className="p-4 md:p-6"><Notice>
          No prompt store is configured. Set <code>ANONYMIZER_PROMPTS=local</code> or <code>langfuse</code> on the API, see docs/prompts.md.
        </Notice></div>
      </>
    );
  }
  return (
    <>
      <PageHeader title="Prompts" description={`${sources.prompts.backend}${sources.prompts.location ? ` · ${sources.prompts.location}` : ""} · agents create drafts, admins promote`} />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <Card><CardHeader><CardDescription>Prompts</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={560}><Table><TableHeader><TableRow>
              {["Name", "Latest", "Labels", "Versions", "Updated"].map(h => <TableHead key={h}>{h}</TableHead>)}
            </TableRow></TableHeader>
              <TableBody>{prompts.map(p => (
                <TableRow key={p.name}>
                  <TableCell className="font-medium"><Link className="underline-offset-2 hover:underline" href={`/prompts/${encodeURIComponent(p.name)}`}>{p.name}</Link></TableCell>
                  <TableCell>v{p.latest_version}</TableCell>
                  <TableCell className="space-x-1">{Object.entries(p.labels).map(([l, v]) => <Pill key={l} value={`${l} v${v}`} />)}
                    {!Object.keys(p.labels).length && <span className="text-muted-foreground">–</span>}</TableCell>
                  <TableCell className="tabular-nums">{p.versions}</TableCell>
                  <TableCell>{ago(p.updated_at)}</TableCell>
                </TableRow>))}
                {!prompts.length && <TableRow><TableCell colSpan={5} className="text-muted-foreground py-6 text-center">No prompts yet</TableCell></TableRow>}
              </TableBody></Table></TableScroll>
          </CardContent></Card>
        <p className="text-muted-foreground text-xs">
          Every new version is checked before it is saved: customer data and OpenAnonymizer placeholders are rejected. Creating a version never moves a label.
        </p>
      </div>
    </>
  );
}

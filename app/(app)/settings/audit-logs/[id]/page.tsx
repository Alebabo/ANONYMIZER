import Link from "next/link";
import { notFound } from "next/navigation";
import { ActionBadge, Actor, SnapshotDiff } from "@/components/audit";
import { Notice, SourceBanner, dateTime } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { ApiError, getAuditEntry } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

export default async function AuditEntryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let res;
  try {
    res = await getAuditEntry(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    if (e instanceof ApiError && e.status === 403)
      return <div className="p-4 md:p-6"><Notice>The audit log is visible to admins only.</Notice></div>;
    throw e;
  }
  const { data: e, source } = res;
  if (!e) notFound();
  return (
    <>
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <Link href="/settings/audit-logs" className="text-link hover:text-link-hover text-xs">← Audit Logs</Link>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2"><CardHeader><CardDescription>Changes</CardDescription></CardHeader>
            <CardContent><SnapshotDiff before={e.before} after={e.after} /></CardContent></Card>
          <Card><CardHeader><CardDescription>Entry</CardDescription></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                <dt className="text-muted-foreground">Time</dt><dd>{dateTime(e.created_at)}</dd>
                <dt className="text-muted-foreground">Action</dt><dd><ActionBadge action={e.action} /></dd>
                <dt className="text-muted-foreground">Actor</dt><dd className="min-w-0"><Actor e={e} /></dd>
                <dt className="text-muted-foreground">Actor id</dt><dd className="font-mono break-all">{e.actor_id ?? "–"}</dd>
                <dt className="text-muted-foreground">Resource</dt><dd className="font-mono break-all">{e.resource_type} / {e.resource_id}</dd>
                <dt className="text-muted-foreground">Entry id</dt><dd className="font-mono break-all">{e.id}</dd>
                <dt className="text-muted-foreground">Hash</dt><dd className="font-mono break-all">{e.hash}</dd>
                <dt className="text-muted-foreground">Previous</dt><dd className="font-mono break-all">{e.prev_hash}</dd>
              </dl>
            </CardContent></Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {(["before", "after"] as const).map(k => (
            <Card key={k}><CardHeader><CardDescription>{k === "before" ? "Before" : "After"} (raw)</CardDescription></CardHeader>
              <CardContent>
                <pre className="bg-surface-code overflow-auto rounded-md p-3 font-mono text-xs">{e[k] == null ? "null" : JSON.stringify(e[k], null, 2)}</pre>
              </CardContent></Card>
          ))}
        </div>
      </div>
    </>
  );
}

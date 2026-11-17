import Link from "next/link";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { TableScroll } from "@/components/app-shell";
import { ActionBadge, Actor, JsonCell } from "@/components/audit";
import { Notice, SourceBanner, dateTime } from "@/components/dashboard";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, getAuditLogs, verifyAudit, type AuditQuery } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

const selectCls = "border-input bg-background h-8 rounded-md border px-2 text-sm";

export default async function AuditLogs({ searchParams }: { searchParams: Promise<AuditQuery> }) {
  const q = await searchParams;
  let page, verify;
  try {
    [page, verify] = await Promise.all([getAuditLogs(q), verifyAudit()]);
  } catch (e) {
    if (e instanceof ApiError && e.status === 403)
      return <div className="p-4 md:p-6"><Notice>The audit log is visible to admins only.</Notice></div>;
    throw e;
  }
  const { data, source } = page;
  const v = verify.data;
  const filtered = Boolean(q.action || q.resource_type);
  const qs = (extra: Record<string, string | number | undefined>) => {
    const p = new URLSearchParams();
    for (const [k, val] of Object.entries({ action: q.action, resource_type: q.resource_type, ...extra })) if (val) p.set(k, String(val));
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  return (
    <>
      <SourceBanner source={source} />
      <div className="space-y-3 p-4 md:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <form className="flex flex-wrap items-center gap-2" method="get">
            <select name="resource_type" defaultValue={q.resource_type ?? ""} className={selectCls} aria-label="Resource type">
              <option value="">All resource types</option>
              {data.resource_types.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select name="action" defaultValue={q.action ?? ""} className={selectCls} aria-label="Action">
              <option value="">All actions</option>
              {data.actions.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            <Button type="submit" variant="outline">Filter</Button>
            {filtered && <Link href="/settings/audit-logs" className="text-link hover:text-link-hover text-xs">Reset</Link>}
          </form>
          <div className={v.ok ? "text-dark-green flex items-center gap-1.5 text-xs" : "text-dark-red flex items-center gap-1.5 text-xs"}
               title={v.head ? `Chain head ${v.head}` : undefined}>
            {v.ok ? <ShieldCheck className="h-4 w-4" /> : <ShieldAlert className="h-4 w-4" />}
            {v.ok ? `Hash chain intact · ${v.entries} entries` : `Hash chain broken at ${v.broken_at}`}
          </div>
        </div>
        <TableScroll minWidth={1080}>
          <div className="rounded-md border">
            <Table><TableHeader><TableRow>
              {["Timestamp", "Actor", "Resource Type", "Resource ID", "Action", "Before", "After"].map(h => <TableHead key={h}>{h}</TableHead>)}
            </TableRow></TableHeader>
              <TableBody>{data.data.map(e => (
                <TableRow key={e.id} className="align-top">
                  <TableCell className="whitespace-nowrap">
                    <Link className="text-link hover:text-link-hover" href={`/settings/audit-logs/${e.id}`}>{dateTime(e.created_at)}</Link>
                  </TableCell>
                  <TableCell className="max-w-56"><Actor e={e} /></TableCell>
                  <TableCell className="font-mono">{e.resource_type}</TableCell>
                  <TableCell className="max-w-40 truncate font-mono" title={e.resource_id}>{e.resource_id}</TableCell>
                  <TableCell><ActionBadge action={e.action} /></TableCell>
                  <TableCell><JsonCell value={e.before} other={e.after} /></TableCell>
                  <TableCell><JsonCell value={e.after} other={e.before} /></TableCell>
                </TableRow>))}
                {!data.data.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground py-6 text-center">No entries</TableCell></TableRow>}
              </TableBody></Table>
          </div>
        </TableScroll>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Newest first · append-only · no content, keys or passwords are recorded</span>
          <div className="flex gap-2">
            {q.before && <Button asChild variant="outline" size="sm"><Link href={`/settings/audit-logs${qs({})}`}>Newest</Link></Button>}
            {data.next_before && <Button asChild variant="outline" size="sm"><Link href={`/settings/audit-logs${qs({ before: data.next_before })}`}>Older</Link></Button>}
          </div>
        </div>
      </div>
    </>
  );
}

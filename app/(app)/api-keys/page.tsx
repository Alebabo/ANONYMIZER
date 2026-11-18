import { revokeApiKey } from "@/app/actions";
import { CreateKeyForm } from "@/app/(app)/api-keys/create-form";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Notice, Pill, SourceBanner, ago, dateTime } from "@/components/dashboard";
import { InlineAction } from "@/components/forms";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getApiKeys, getMe, getMembers } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

export default async function ApiKeys() {
  const [{ data: keys, source }, { data: me }, { data: members }] = await Promise.all([getApiKeys(), getMe(), getMembers()]);
  const admin = me.role === "admin" && source.live;
  const who = (id: string | null) => members.find(m => m.id === id)?.email ?? (id ? id : "system");
  const active = keys.filter(k => !k.revoked_at);
  return (
    <>
      <PageHeader section="setup" title="API Keys" description={`${active.length} active · keys belong to ${me.organization.name}`} />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <Card><CardHeader><CardDescription>Create a key</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {!admin && <Notice>{source.live ? "Only admins can create or revoke keys." : "Demo mode: changes are disabled."}</Notice>}
            <CreateKeyForm disabled={!admin} />
          </CardContent></Card>
        <Card><CardHeader><CardDescription>Keys</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={760}><Table><TableHeader><TableRow>
              {["Name", "Key", "Role", "Created", "Last used", "Status", ""].map(h => <TableHead key={h}>{h}</TableHead>)}
            </TableRow></TableHeader>
              <TableBody>{keys.map(k => (
                <TableRow key={k.id} className={k.revoked_at ? "opacity-60" : undefined}>
                  <TableCell className="font-medium">{k.name}</TableCell>
                  <TableCell className="font-mono">{k.prefix}…</TableCell>
                  <TableCell><Pill value={k.role} /></TableCell>
                  <TableCell title={`by ${who(k.created_by)}`}>{dateTime(k.created_at)}</TableCell>
                  <TableCell>{ago(k.last_used_at)}</TableCell>
                  <TableCell>{k.revoked_at ? `revoked ${dateTime(k.revoked_at)}` : <Pill value="active" />}</TableCell>
                  <TableCell className="text-right">
                    {admin && !k.revoked_at && (
                      <InlineAction action={revokeApiKey} fields={{ id: k.id }} label="Revoke" variant="destructive-secondary"
                                    confirm={`Revoke "${k.name}"? Applications using it stop working immediately.`} />
                    )}
                  </TableCell>
                </TableRow>))}
                {!keys.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground py-6 text-center">No keys yet</TableCell></TableRow>}
              </TableBody></Table></TableScroll>
          </CardContent></Card>
        <p className="text-muted-foreground text-xs">
          Keys are shown once and stored as SHA-256 hashes. Keys from <code>ANONYMIZER_API_KEYS</code> / <code>ANONYMIZER_ADMIN_KEYS</code> keep
          working and are not listed here. Creating and revoking keys is recorded in the audit log.
        </p>
      </div>
    </>
  );
}

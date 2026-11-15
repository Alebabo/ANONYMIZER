import { createMember, updateMember } from "@/app/actions";
import { TableScroll } from "@/components/app-shell";
import { Notice, Pill, SourceBanner, ago, dateTime } from "@/components/dashboard";
import { ActionForm, Field, InlineAction, Select, Submit } from "@/components/forms";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getMe, getMembers } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

export default async function Members() {
  const [{ data: members, source }, { data: me }] = await Promise.all([getMembers(), getMe()]);
  const admin = me.role === "admin" && source.live;
  return (
    <>
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <Card><CardHeader><CardDescription>Members of {me.organization.name}</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={760}><Table><TableHeader><TableRow>
              {["Name", "E-mail", "Role", "Last login", "Added", "Status", ""].map(h => <TableHead key={h}>{h}</TableHead>)}
            </TableRow></TableHeader>
              <TableBody>{members.map(m => {
                const self = m.id === me.user?.id;
                return (
                  <TableRow key={m.id} className={m.disabled ? "opacity-60" : undefined}>
                    <TableCell className="font-medium">{m.name}{self && <span className="text-muted-foreground"> (you)</span>}</TableCell>
                    <TableCell>{m.email}</TableCell>
                    <TableCell><Pill value={m.role} /></TableCell>
                    <TableCell>{ago(m.last_login_at)}</TableCell>
                    <TableCell>{dateTime(m.created_at)}</TableCell>
                    <TableCell><Pill value={m.disabled ? "disabled" : "active"} /></TableCell>
                    <TableCell>
                      {admin && !self && (
                        <div className="flex justify-end gap-2">
                          <InlineAction action={updateMember} fields={{ id: m.id, role: m.role === "admin" ? "member" : "admin" }}
                                        label={m.role === "admin" ? "Make member" : "Make admin"} />
                          <InlineAction action={updateMember} fields={{ id: m.id, disabled: m.disabled ? "false" : "true" }}
                                        label={m.disabled ? "Enable" : "Disable"} variant={m.disabled ? "outline" : "destructive-secondary"}
                                        confirm={m.disabled ? undefined : `Disable ${m.email}? Active sessions end immediately.`} />
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}</TableBody></Table></TableScroll>
          </CardContent></Card>
        <Card><CardHeader><CardDescription>Add member</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {!admin && <Notice>{source.live ? "Only admins can add members." : "Demo mode: changes are disabled."}</Notice>}
            <ActionForm action={createMember} resetOnSuccess>
              <fieldset disabled={!admin} className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_9rem_auto] xl:items-start">
                <Field label="Name"><Input name="name" required maxLength={100} /></Field>
                <Field label="E-mail"><Input name="email" type="email" required /></Field>
                <Field label="Initial password" hint="Min. 12 characters; the member changes it in Settings">
                  <Input name="password" type="password" minLength={12} required autoComplete="new-password" />
                </Field>
                <Field label="Role">
                  <Select name="role" defaultValue="member"><option value="member">member</option><option value="admin">admin</option></Select>
                </Field>
                <Submit pendingText="Adding…" className="xl:mt-[22px]">Add member</Submit>
              </fieldset>
            </ActionForm>
            <p className="text-muted-foreground text-xs">
              <b>admin</b>: manage keys, members and organization settings, read the audit log.{" "}
              <b>member</b>: read-only access to traces, metrics, policies and keys.
            </p>
          </CardContent></Card>
      </div>
    </>
  );
}

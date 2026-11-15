import { changePassword, updateOrganization } from "@/app/actions";
import { Notice, SourceBanner, dateTime } from "@/components/dashboard";
import { ActionForm, Field, Submit } from "@/components/forms";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getMe } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

export default async function GeneralSettings() {
  const { data: me, source } = await getMe();
  const org = me.organization;
  const admin = me.role === "admin" && source.live;
  return (
    <>
      <SourceBanner source={source} />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-2">
        <Card><CardHeader><CardDescription>Organization</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {!admin && <Notice>{source.live ? "Only admins can change organization settings." : "Demo mode: changes are disabled."}</Notice>}
            <ActionForm action={updateOrganization}>
              <fieldset disabled={!admin} className="space-y-3">
                <Field label="Name"><Input name="name" defaultValue={org.name} required maxLength={100} /></Field>
                <Field label="Trace retention (days)"
                       hint={`Traces are metadata only. Empty = server default; currently ${org.effective_trace_retention_days} days.`}>
                  <Input name="trace_retention_days" type="number" min={1} max={3650}
                         defaultValue={org.trace_retention_days ?? ""} placeholder={String(org.effective_trace_retention_days)} />
                </Field>
                <Submit>Save</Submit>
              </fieldset>
            </ActionForm>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-t pt-3 text-xs">
              <dt className="text-muted-foreground">Organization id</dt><dd className="font-mono">{org.id}</dd>
              <dt className="text-muted-foreground">Created</dt><dd>{dateTime(org.created_at)}</dd>
            </dl>
          </CardContent></Card>
        <Card><CardHeader><CardDescription>Your account</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {me.user ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                <dt className="text-muted-foreground">Name</dt><dd>{me.user.name}</dd>
                <dt className="text-muted-foreground">E-mail</dt><dd>{me.user.email}</dd>
                <dt className="text-muted-foreground">Role</dt><dd>{me.user.role}</dd>
                <dt className="text-muted-foreground">Last login</dt><dd>{dateTime(me.user.last_login_at)}</dd>
              </dl>
            ) : <Notice>Signed in with an API key.</Notice>}
            <ActionForm action={changePassword} resetOnSuccess className="border-t pt-3">
              <fieldset disabled={!source.live} className="space-y-3">
                <Field label="Current password">
                  <Input name="current_password" type="password" autoComplete="current-password" required allowPasswordManager />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="New password" hint="At least 12 characters">
                    <Input name="new_password" type="password" autoComplete="new-password" minLength={12} required allowPasswordManager />
                  </Field>
                  <Field label="Repeat new password">
                    <Input name="confirm_password" type="password" autoComplete="new-password" minLength={12} required allowPasswordManager />
                  </Field>
                </div>
                <Submit variant="outline">Change password</Submit>
              </fieldset>
            </ActionForm>
          </CardContent></Card>
      </div>
    </>
  );
}

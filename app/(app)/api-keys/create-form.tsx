"use client";
import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { createApiKey } from "@/app/actions";
import { ActionForm, Field, Select, Submit } from "@/components/forms";
import { Input } from "@/components/ui/input";

function OneTimeKey({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="bg-light-green mt-3 space-y-2 rounded-md p-3">
      <p className="text-dark-green text-xs font-medium">Copy the key now. It is stored as a hash and cannot be shown again.</p>
      <div className="flex gap-2">
        <code className="bg-background min-w-0 flex-1 truncate rounded-md border px-2 py-1.5 font-mono text-xs">{value}</code>
        <button type="button" aria-label="Copy key" className="hover:bg-background/60 flex h-8 w-8 items-center justify-center rounded-md"
                onClick={() => navigator.clipboard.writeText(value).then(() => setCopied(true))}>
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}

export function CreateKeyForm({ disabled }: { disabled: boolean }) {
  return (
    <ActionForm action={createApiKey} resetOnSuccess render={s => s.key && <OneTimeKey value={s.key} />}>
      <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
        <Field label="Name" hint="What uses this key, e.g. contract review backend">
          <Input name="name" required maxLength={100} placeholder="Contract review backend" />
        </Field>
        <Field label="Role" hint="admin: restore & policy writes">
          <Select name="role" defaultValue="user">
            <option value="user">user</option>
            <option value="admin">admin</option>
          </Select>
        </Field>
        <Submit pendingText="Creating…" className="sm:mb-5">Create key</Submit>
      </fieldset>
    </ActionForm>
  );
}

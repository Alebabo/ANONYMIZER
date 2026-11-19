"use client";
import { setPromptLabel } from "@/app/actions";
import { ActionForm, Field, Select, Submit } from "@/components/forms";
import { Input } from "@/components/ui/input";

export function PromoteForm({ name, version, disabled }: { name: string; version: number; disabled: boolean }) {
  return (
    <ActionForm action={setPromptLabel}>
      <input type="hidden" name="name" value={name} />
      <fieldset disabled={disabled} className="grid gap-3">
        <Field label="Version">
          <Input name="version" type="number" min={1} required defaultValue={version} />
        </Field>
        <Field label="Label" hint="production is what your application serves">
          <Select name="label" defaultValue="production">
            <option value="production">production</option>
            <option value="staging">staging</option>
          </Select>
        </Field>
        <Submit pendingText="Moving…">Set label</Submit>
      </fieldset>
    </ActionForm>
  );
}

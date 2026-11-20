"use client";
import { Fragment, useState } from "react";
import { FlaskConical, Save } from "lucide-react";
import { editPolicy, type ActionState } from "@/app/actions";
import { ActionForm, Submit } from "@/components/forms";
import { Chip, Collapsible } from "@/components/widgets";
import { ACTIONS, actionLabel, describeRule, editorTypes, entityActions, isSimple, type PolicyJson } from "@/lib/policy-edit";
import { cn } from "@/lib/utils";

const selectCls = "border-input bg-background h-8 w-full rounded-md border px-2 text-sm";

function ActionSelect({ name, value, onChange, defaultLabel, changed }: {
  name: string; value: string; onChange: (v: string) => void; defaultLabel?: string; changed: boolean;
}) {
  return (
    <select name={name} value={value} onChange={e => onChange(e.target.value)}
            className={cn(selectCls, changed && "border-dark-yellow bg-light-yellow")}>
      {defaultLabel && <option value="">{defaultLabel}</option>}
      {ACTIONS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
    </select>
  );
}

function Output({ title, text, reasons, outcome, changed }: {
  title: string; text: string | null; reasons: string[]; outcome: string; changed?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="text-muted-foreground mb-1 flex items-center gap-1.5">{title}<Chip>{outcome}</Chip></div>
      {text != null ? (
        <pre className={cn("rounded-md border p-2 font-mono whitespace-pre-wrap break-words",
          changed ? "border-dark-yellow bg-light-yellow" : "bg-background")}>{text}</pre>
      ) : (
        <div className="bg-light-red text-dark-red rounded-md p-2">Not sent{reasons.length ? `: ${reasons.join("; ")}` : ""}</div>
      )}
    </div>
  );
}

function Diff({ diff }: { diff: NonNullable<ActionState["diff"]> }) {
  return (
    <div className="bg-muted/50 mt-3 space-y-3 rounded-md p-3 text-xs">
      <div className="grid gap-3 md:grid-cols-2">
        <Output title="Now" text={diff.text_before} reasons={diff.reasons_before} outcome={diff.outcome_before} />
        <Output title="With your changes" text={diff.text_after} reasons={diff.reasons_after} outcome={diff.outcome_after}
                changed={diff.text_after !== diff.text_before} />
      </div>
      {diff.changes.length > 0 && (
        <ul className="space-y-1">
          {diff.changes.map((c, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1.5">
              <Chip>{c.entity_type}</Chip>{actionLabel(c.before)} → <b>{actionLabel(c.after)}</b>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PolicyEditor({ policy, canEdit }: { policy: PolicyJson; canEdit: boolean }) {
  const saved = entityActions(policy);
  const [actions, setActions] = useState<Record<string, string>>(saved);
  const [fallback, setFallback] = useState(policy.default_action);
  const groups = editorTypes(policy);
  const advanced = policy.rules.filter(r => !isSimple(r));
  const changes = groups.flatMap(g => g.types).filter(([t]) => (actions[t] ?? "") !== (saved[t] ?? "")).length
    + (fallback !== policy.default_action ? 1 : 0);
  const defaultLabel = `Default (${actionLabel(fallback)})`;

  return (
    <ActionForm action={editPolicy} keepValues className="space-y-4" render={s => s.diff && <Diff diff={s.diff} />}>
      <input type="hidden" name="name" value={policy.name} />
      <input type="hidden" name="version" value={policy.version} />
      <fieldset disabled={!canEdit} className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map(g => (
            <section key={g.title} className="bg-card rounded-lg border p-3">
              <h3 className="mb-2 text-xs font-medium">{g.title}</h3>
              <div className="space-y-1.5">
                {g.types.map(([t, label]) => (
                  <label key={t} className="grid grid-cols-[1fr_9.5rem] items-center gap-2 text-sm">
                    <span className="truncate" title={t}>{label}</span>
                    <ActionSelect name={`entity:${t}`} value={actions[t] ?? ""} defaultLabel={defaultLabel}
                                  changed={(actions[t] ?? "") !== (saved[t] ?? "")}
                                  onChange={v => setActions(a => ({ ...a, [t]: v }))} />
                  </label>
                ))}
              </div>
            </section>
          ))}
          <section className="bg-card rounded-lg border p-3">
            <h3 className="mb-2 text-xs font-medium">Everything else</h3>
            <label className="grid grid-cols-[1fr_9.5rem] items-center gap-2 text-sm">
              <span>Default</span>
              <ActionSelect name="default_action" value={fallback} onChange={setFallback} changed={fallback !== policy.default_action} />
            </label>
            <p className="text-muted-foreground mt-2 text-2xs">For data types without their own setting.</p>
          </section>
        </div>

        <section className="bg-card rounded-lg border p-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium">Try it before saving</span>
            <textarea name="sample" rows={3} placeholder="e.g. Herr Max Mustermann (max@example.org, IBAN DE89 3704 0044 0532 0130 00) bittet um Rückruf."
                      className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm" />
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Submit name="intent" value="test" variant="outline" size="sm" pendingText="Testing…">
              <FlaskConical className="h-3.5 w-3.5" />Test changes
            </Submit>
            <Submit name="intent" value="save" size="sm" disabled={!changes}>
              <Save className="h-3.5 w-3.5" />Save as v{policy.version + 1}
            </Submit>
            <span className="text-muted-foreground text-xs">
              {changes ? `${changes} change(s) not saved` : "No changes"}{!canEdit && " · only admins can change policies"}
            </span>
          </div>
        </section>

        {advanced.length > 0 && (
          <Collapsible title="Always applied" summary={`${advanced.length + (policy.critical_floor ? 1 : 0)} rule(s), not changed here`}>
            <ul className="text-muted-foreground list-disc space-y-0.5 pl-4 text-xs">
              {advanced.map((r, i) => <li key={r.id ?? i}>{describeRule(r)}</li>)}
              {policy.critical_floor && <li>Highly sensitive values never leave unchanged, even if set to Keep → {actionLabel(policy.critical_floor_action ?? "pseudonymize")}</li>}
            </ul>
          </Collapsible>
        )}

        <Collapsible title="What the options do">
          <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[8rem_1fr]">
            {ACTIONS.map(a => <Fragment key={a.value}><dt className="font-medium">{a.label}</dt><dd className="text-muted-foreground">{a.example}</dd></Fragment>)}
          </dl>
        </Collapsible>
      </fieldset>
    </ActionForm>
  );
}

"use client";
import { startTransition, useActionState, useEffect, useRef } from "react";
import { useFormStatus } from "react-dom";
import { Button, type ButtonProps } from "@/components/ui/button";
import type { ActionState } from "@/app/actions";
import { cn } from "@/lib/utils";

type Action = (state: ActionState, form: FormData) => Promise<ActionState>;

/**
 * Form bound to a server action; shows the action's error or success message below the fields.
 * `keepValues` submits without React's automatic form reset, for editors whose fields stay in use.
 */
export function ActionForm({ action, children, className, resetOnSuccess, keepValues, render }: {
  action: Action; children: React.ReactNode; className?: string; resetOnSuccess?: boolean; keepValues?: boolean;
  render?: (state: ActionState) => React.ReactNode;
}) {
  const [state, formAction] = useActionState(action, {});
  const ref = useRef<HTMLFormElement>(null);
  useEffect(() => { if (resetOnSuccess && state.ok) ref.current?.reset(); }, [state, resetOnSuccess]);
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget, (e.nativeEvent as SubmitEvent).submitter);
    startTransition(() => formAction(data));
  };
  return (
    <form ref={ref} action={keepValues ? undefined : formAction} onSubmit={keepValues ? submit : undefined} className={className}>
      {children}
      <Feedback state={state} />
      {render?.(state)}
    </form>
  );
}

export function Feedback({ state }: { state: ActionState }) {
  if (state.error) return <p role="alert" className="text-dark-red mt-2 text-xs">{state.error}</p>;
  if (state.message) return <p role="status" className="text-dark-green mt-2 text-xs">{state.message}</p>;
  return null;
}

export function Submit({ children, pendingText = "Saving…", ...props }: ButtonProps & { pendingText?: string }) {
  const { pending } = useFormStatus();
  return <Button type="submit" loading={pending} loadingText={pendingText} {...props}>{children}</Button>;
}

export function Field({ label, hint, children, className }: {
  label: string; hint?: string; children: React.ReactNode; className?: string;
}) {
  return (
    <label className={cn("block space-y-1", className)}>
      <span className="text-xs font-medium">{label}</span>
      {children}
      {hint && <span className="text-muted-foreground block text-2xs">{hint}</span>}
    </label>
  );
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("border-input bg-background h-8 w-full rounded-md border px-2 text-sm disabled:opacity-50", className)}
      {...props}
    />
  );
}

/** Small inline form with one submit button (revoke, disable, role change). */
export function InlineAction({ action, fields, label, variant = "outline", confirm }: {
  action: Action; fields: Record<string, string>; label: string; variant?: ButtonProps["variant"]; confirm?: string;
}) {
  const [state, formAction] = useActionState(action, {});
  return (
    <form action={formAction} className="inline-flex flex-col items-end"
          onSubmit={e => { if (confirm && !window.confirm(confirm)) e.preventDefault(); }}>
      {Object.entries(fields).map(([k, v]) => <input key={k} type="hidden" name={k} value={v} />)}
      <Submit size="sm" variant={variant} pendingText="…">{label}</Submit>
      {state.error && <span role="alert" className="text-dark-red mt-1 max-w-48 text-right text-2xs">{state.error}</span>}
    </form>
  );
}

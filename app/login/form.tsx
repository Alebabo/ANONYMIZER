"use client";
import { useActionState } from "react";
import { login } from "@/app/actions";
import { Feedback, Field, Submit } from "@/components/forms";
import { Input } from "@/components/ui/input";

export function LoginForm({ next }: { next: string }) {
  const [state, action] = useActionState(login, {});
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="next" value={next} />
      <Field label="E-mail">
        <Input key={state.email} name="email" type="email" autoComplete="username" required autoFocus={!state.email}
               defaultValue={state.email} allowPasswordManager />
      </Field>
      <Field label="Password">
        <Input name="password" type="password" autoComplete="current-password" required autoFocus={Boolean(state.email)}
               allowPasswordManager />
      </Field>
      <Submit className="w-full" pendingText="Signing in…">Sign in</Submit>
      <Feedback state={state} />
    </form>
  );
}

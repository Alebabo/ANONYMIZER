"use server";
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, SESSION_COOKIE, api, apiLogin, isDemo, type ApiKey } from "@/lib/anonymizer-api";

/**
 * Server actions. Next.js checks the Origin header of every action (CSRF protection);
 * the API checks roles and organization scope for every call.
 */

export type ActionState = { ok?: boolean; error?: string; message?: string; key?: string; email?: string };

const DEMO: ActionState = { error: "Demo mode: connect the API (ANONYMIZER_API_URL) to make changes." };

async function run(fn: () => Promise<ActionState | void>, path: string): Promise<ActionState> {
  if (isDemo()) return DEMO;
  try {
    const out = await fn();
    revalidatePath(path);
    return { ok: true, ...(out ?? {}) };
  } catch (e) {
    if (e instanceof ApiError) return { error: e.message };
    throw e; // redirects and unexpected errors
  }
}

const str = (f: FormData, k: string) => String(f.get(k) ?? "").trim();

function safeNext(value: string): string {
  return value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/login") ? value : "/";
}

export async function login(_: ActionState, form: FormData): Promise<ActionState> {
  if (isDemo()) return DEMO;
  let session;
  try {
    session = await apiLogin(str(form, "email"), String(form.get("password") ?? ""));
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Anonymizer API not reachable.", email: str(form, "email") };
  }
  (await cookies()).set(SESSION_COOKIE, session.token, {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/",
    expires: new Date(session.expires_at * 1000),
  });
  redirect(safeNext(str(form, "next")));
}

export async function logout(): Promise<void> {
  const jar = await cookies();
  if (!isDemo() && jar.get(SESSION_COOKIE)) {
    try { await api("/v1/auth/logout", { method: "POST" }); } catch { /* session already gone */ }
  }
  jar.delete(SESSION_COOKIE);
  redirect("/login");
}

export async function createApiKey(_: ActionState, form: FormData): Promise<ActionState> {
  return run(async () => {
    const key = await api<ApiKey & { key: string }>("/v1/api-keys", {
      method: "POST", body: JSON.stringify({ name: str(form, "name"), role: str(form, "role") || "user" }),
    });
    return { key: key.key, message: `Key "${key.name}" created.` };
  }, "/api-keys");
}

export async function revokeApiKey(_: ActionState, form: FormData): Promise<ActionState> {
  return run(async () => {
    await api(`/v1/api-keys/${encodeURIComponent(str(form, "id"))}`, { method: "DELETE" });
    return { message: "Key revoked." };
  }, "/api-keys");
}

export async function createMember(_: ActionState, form: FormData): Promise<ActionState> {
  return run(async () => {
    await api("/v1/members", {
      method: "POST",
      body: JSON.stringify({ email: str(form, "email"), name: str(form, "name"), role: str(form, "role") || "member",
                             password: String(form.get("password") ?? "") }),
    });
    return { message: "Member added. Share the initial password through a separate channel." };
  }, "/settings/members");
}

export async function updateMember(_: ActionState, form: FormData): Promise<ActionState> {
  const body: Record<string, unknown> = {};
  if (form.get("role")) body.role = str(form, "role");
  if (form.get("disabled")) body.disabled = str(form, "disabled") === "true";
  return run(async () => {
    await api(`/v1/members/${encodeURIComponent(str(form, "id"))}`, { method: "PATCH", body: JSON.stringify(body) });
  }, "/settings/members");
}

export async function updateOrganization(_: ActionState, form: FormData): Promise<ActionState> {
  const retention = str(form, "trace_retention_days");
  return run(async () => {
    await api("/v1/organization", {
      method: "PATCH",
      body: JSON.stringify({ name: str(form, "name"), ...(retention ? { trace_retention_days: Number(retention) } : {}) }),
    });
    return { message: "Saved." };
  }, "/settings");
}

export async function changePassword(_: ActionState, form: FormData): Promise<ActionState> {
  const next = String(form.get("new_password") ?? "");
  if (next !== String(form.get("confirm_password") ?? "")) return { error: "The new passwords do not match." };
  return run(async () => {
    await api("/v1/auth/password", {
      method: "POST", body: JSON.stringify({ current_password: String(form.get("current_password") ?? ""), new_password: next }),
    });
    return { message: "Password changed. Other sessions were signed out." };
  }, "/settings");
}

export async function setPromptLabel(_: ActionState, form: FormData): Promise<ActionState> {
  const name = str(form, "name");
  return run(async () => {
    const out = await api<{ version: number; previous_version: number | null; label: string }>(
      `/v1/prompts/${encodeURIComponent(name)}/labels`,
      { method: "POST", body: JSON.stringify({ version: Number(str(form, "version")), label: str(form, "label") }) });
    return { message: `${out.label} → v${out.version}` + (out.previous_version ? ` (was v${out.previous_version})` : "") };
  }, `/prompts/${encodeURIComponent(name)}`);
}

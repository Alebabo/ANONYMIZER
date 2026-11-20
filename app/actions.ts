"use server";
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, SESSION_COOKIE, api, apiLogin, isDemo, type ApiKey } from "@/lib/anonymizer-api";
import { applyChanges, type PolicyJson } from "@/lib/policy-edit";

/**
 * Server actions. Next.js checks the Origin header of every action (CSRF protection);
 * the API checks roles and organization scope for every call.
 */

export type ActionState = {
  ok?: boolean; error?: string; message?: string; key?: string; email?: string;
  /** Policy test run: what the candidate would change on the sample text. */
  diff?: {
    outcome_before: string; outcome_after: string; changes: { entity_type: string; before: string; after: string }[];
    /** The sample as it would leave OpenAnonymizer; null = not sent. */
    text_before: string | null; text_after: string | null; reasons_before: string[]; reasons_after: string[];
  };
};

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
    return { error: e instanceof ApiError ? e.message : "OpenAnonymizer API not reachable.", email: str(form, "email") };
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

// -- playground ------------------------------------------------------------------------------
export async function uploadDataset(_: ActionState, form: FormData): Promise<ActionState> {
  if (isDemo()) return DEMO;
  const file = form.get("file");
  if (!(file instanceof File) || !file.size) return { error: "Choose a CSV file." };
  if (file.size > 100 * 1024 * 1024) return { error: "File larger than 100 MB." };
  let id: string;
  try {
    const ds = await api<{ id: string }>("/v1/playground/datasets", {
      method: "POST", body: JSON.stringify({ name: file.name.slice(0, 120), csv: await file.text() }),
    });
    id = ds.id;
  } catch (e) {
    if (e instanceof ApiError) return { error: e.message };
    throw e;
  }
  revalidatePath("/playground");
  redirect(`/playground?ds=${encodeURIComponent(id)}`);
}

export async function deleteDataset(_: ActionState, form: FormData): Promise<ActionState> {
  if (isDemo()) return DEMO;
  try {
    await api(`/v1/playground/datasets/${encodeURIComponent(str(form, "id"))}`, { method: "DELETE" });
  } catch (e) {
    if (e instanceof ApiError) return { error: e.message };
    throw e;
  }
  revalidatePath("/playground");
  redirect("/playground");
}

/** Hidden columns stay stored but are never searched, shown or sent (dashboard and MCP). */
export async function setHiddenColumns(_: ActionState, form: FormData): Promise<ActionState> {
  if (isDemo()) return DEMO;
  const shown = new Set(form.getAll("show").map(String));
  const hidden = form.getAll("column").map(String).filter(c => !shown.has(c));
  return run(async () => {
    await api(`/v1/playground/datasets/${encodeURIComponent(str(form, "id"))}/columns`, {
      method: "PUT", body: JSON.stringify({ hidden }),
    });
    return { message: hidden.length ? `${hidden.length} column(s) hidden, also for Claude.` : "All columns visible." };
  }, "/playground");
}

// -- policies --------------------------------------------------------------------------------
/** Simple editor: "test" compares the edited policy with the saved one on a sample text, "save" stores it as the next version. */
export async function editPolicy(_: ActionState, form: FormData): Promise<ActionState> {
  const name = str(form, "name");
  return run(async () => {
    const current = await api<PolicyJson>(`/v1/policies/${encodeURIComponent(name)}`);
    if (current.version !== Number(str(form, "version")))
      return { error: `${name} was changed meanwhile (now v${current.version}). Reload the page.` };
    const wanted: Record<string, string> = {};
    for (const [k, v] of form.entries()) if (k.startsWith("entity:")) wanted[k.slice(7)] = String(v);
    const defaultAction = str(form, "default_action") || current.default_action;
    if (str(form, "intent") === "test") {
      const text = str(form, "sample");
      if (!text) return { error: "Enter a sample text to test with." };
      // Same endpoint API clients use: POST /v1/policies/{name}/test ("" = follow the default → null).
      const changes = Object.fromEntries(Object.entries(wanted).map(([t, a]) => [t, a || null]));
      const diff = await api<ActionState["diff"]>(`/v1/policies/${encodeURIComponent(name)}/test`, {
        method: "POST", body: JSON.stringify({ text, changes, default_action: defaultAction, destination: "external" }),
      });
      return { diff, message: diff!.changes.length ? undefined : "No difference on this text." };
    }
    // JSON is valid YAML, so the API parses it like a policy file.
    const yaml = JSON.stringify(applyChanges(current, wanted, defaultAction));
    if (yaml === JSON.stringify({ ...current, version: current.version + 1 })) return { message: "Nothing changed." };
    const saved = await api<{ version: number }>("/v1/policies", { method: "POST", body: JSON.stringify({ yaml }) });
    return { message: `Saved as ${name} v${saved.version}. Applies to new requests right away.` };
  }, "/settings/policies");
}

// -- chat ----------------------------------------------------------------------------------
export type ChatResult = {
  text: string | null; outcome: string; allowed: boolean; reasons: string[]; policy: string;
  entities: Record<string, number>; trace_id: string | null;
} | { error: string };

type ProtectBody = {
  text: string | null; outcome: string; allowed: boolean; trace_id: string | null;
  decision: { policy: string; reasons: string[]; entities: { entity_type: string }[] };
};

/** Chat tab: one message through the model with the chosen policy (POST /v1/protect, traced as "dashboard"). */
export async function protectText(text: string, policy: string): Promise<ChatResult> {
  if (isDemo()) return { error: DEMO.error! };
  if (!text.trim()) return { error: "Enter a text." };
  try {
    const r = await api<ProtectBody>("/v1/protect", {
      method: "POST", body: JSON.stringify({ text, policy: policy || null, destination: "external" }),
    });
    const entities: Record<string, number> = {};
    for (const e of r.decision.entities) entities[e.entity_type] = (entities[e.entity_type] ?? 0) + 1;
    return { text: r.text, outcome: r.outcome, allowed: r.allowed, reasons: r.decision.reasons, policy: r.decision.policy,
             entities, trace_id: r.trace_id };
  } catch (e) {
    if (e instanceof ApiError) return { error: e.message };
    throw e;
  }
}

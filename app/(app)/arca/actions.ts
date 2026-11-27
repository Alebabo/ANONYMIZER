"use server";
import { revalidatePath } from "next/cache";
import { ArcaError, arca, type ArcaAudit, type ArcaPreview, type ArcaSpan } from "@/lib/arca-api";

type Result<T> = { ok: true; data: T } | { ok: false; error: string };

async function call<T>(fn: () => Promise<T>, refresh = false): Promise<Result<T>> {
  try {
    const data = await fn();
    if (refresh) revalidatePath("/arca");
    return { ok: true, data };
  } catch (e) {
    if (e instanceof ArcaError) return { ok: false, error: e.message };
    throw e;
  }
}

export async function arcaPreview(columns: string[]) {
  return call(() => arca<ArcaPreview>("/preview", { columns }));
}

export async function arcaRelease(previewId: string) {
  return call(() => arca<ArcaAudit>("/release", { preview_id: previewId }), true);
}

export async function arcaRevoke() {
  return call(() => arca<ArcaAudit>("/revoke", {}), true);
}

/** Nur für die Anzeige: Klarnamen gehen nie zurück an Claude. */
export async function arcaRetranslate(text: string) {
  return call(() => arca<{ text: string; spans: { start: number; end: number; token: string }[] }>("/retranslate", { text }));
}

export type { ArcaSpan };

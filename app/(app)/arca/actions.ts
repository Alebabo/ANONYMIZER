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

/** Dokument zu einem Mandat: Text bzw. lokales OCR (offline), landet nur in vault.db. */
export async function arcaUpload(form: FormData) {
  const file = form.get("file");
  const mandat = String(form.get("mandat_id") ?? "");
  if (!(file instanceof File) || !file.size) return { ok: false as const, error: "Keine Datei gewählt" };
  if (!/^\d+$/.test(mandat)) return { ok: false as const, error: "Kein Mandat gewählt" };
  const body = new FormData();
  body.set("mandat_id", mandat);
  body.set("file", file, file.name);
  return call(() => arca<{ dateiname: string; ocr: boolean; chars: number }>("/documents", body), true);
}

export type { ArcaSpan };

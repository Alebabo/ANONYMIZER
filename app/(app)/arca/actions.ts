"use server";
import { revalidatePath } from "next/cache";
import {
  ArcaError, arca, requireArcaUser, type ArcaAudit, type ArcaOptions, type ArcaPreview, type ArcaSpan,
} from "@/lib/arca-api";

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

export async function arcaPreview(columns: string[], options: ArcaOptions) {
  return call(() => arca<ArcaPreview>("/preview", { columns, options }));
}

/** Pflichtprüfung: die prüfende Person kommt aus der Sitzung, nicht aus dem Browser. */
export async function arcaRelease(previewId: string, confirmed: boolean) {
  return call(async () => {
    const actor = await requireArcaUser();
    return arca<ArcaAudit>("/release", { preview_id: previewId, confirmed, actor });
  }, true);
}

export async function arcaRevoke() {
  return call(async () => arca<ArcaAudit>("/revoke", { actor: await requireArcaUser() }), true);
}

/** Vorschau einer Frage an Claude: so, wie der Terminal-Server sie pseudonymisiert weitergibt. */
export async function arcaPseudonymize(text: string) {
  return call(() => arca<{ text: string; spans: ArcaSpan[]; hints: string[] }>("/pseudonymize", { text }));
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
  body.set("actor", await requireArcaUser());
  body.set("file", file, file.name);
  return call(() => arca<{ dateiname: string; ocr: boolean; chars: number }>("/documents", body), true);
}

export type { ArcaSpan };

"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { Columns2, FileUp, Lock, MessageSquare, Table2 } from "lucide-react";
import { Widget, stamp } from "@/components/widgets";
import { Button } from "@/components/ui/button";
import type { ArcaOptions, ArcaPreview, ArcaTables } from "@/lib/arca-api";
import { cn } from "@/lib/utils";
import { arcaPreview, arcaRelease, arcaRevoke, arcaUpload } from "./actions";
import { Chat } from "./chat";
import { Highlighted } from "./highlighted";

const ACTIONS: Record<string, [string, string]> = {
  release: ["Freigabe", "text-dark-green"], revoke: ["Widerruf", "text-dark-red"],
  document: ["Dokument (nur vault.db)", "text-dark-blue"],
  chat_message: ["Frage an Claude", "text-dark-violet"], terminal_login_code: ["Claude-Anmeldung", "text-dark-blue"],
  terminal_unlock: ["Direkteingabe freigeschaltet", "text-dark-red"], terminal_lock: ["Direkteingabe gesperrt", "text-dark-green"],
};

/**
 * Schlichtes Tabellenraster wie in Excel: Linien um jede Zelle, eine Zeile pro Datensatz, lange Werte mit "…"
 * abgeschnitten (voller Text beim Darüberfahren), graue Kopfzeile und Zeilennummern, scrollt in beide Richtungen.
 */
function Grid({ head, rows, titles, selected }: {
  head: React.ReactNode[]; rows: React.ReactNode[][]; titles?: string[][]; selected?: boolean[];
}) {
  const cell = "border-border border px-1.5 py-0.5 text-left align-top font-normal whitespace-nowrap";
  return (
    <div className="max-h-[22rem] overflow-auto border-border border">
      <table className="w-max min-w-full border-collapse text-xs">
        <thead className="bg-muted sticky top-0 z-10">
          <tr>
            <th className={cn(cell, "text-muted-foreground w-8 text-right")} />
            {head.map((h, i) => <th key={i} className={cn(cell, selected?.[i] && "bg-accent")}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              <td className={cn(cell, "bg-muted text-muted-foreground text-right tabular-nums")}>{r + 1}</td>
              {row.map((v, c) => (
                <td key={c} title={titles?.[r]?.[c]} className={cn(cell, "max-w-[16rem] overflow-hidden text-ellipsis", selected?.[c] && "bg-accent/40")}>
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type View = "data" | "chat" | "split";
const VIEWS: { key: View; label: string; icon: typeof Table2 }[] = [
  { key: "data", label: "Daten", icon: Table2 },
  { key: "chat", label: "Chat", icon: MessageSquare },
  { key: "split", label: "Geteilt", icon: Columns2 },
];
const VIEW_KEY = "arca-view";

export function ArcaWorkspace({ tables, terminalUrl }: { tables: ArcaTables; terminalUrl: string }) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<ArcaPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const [options, setOptions] = useState<ArcaOptions>({ dates: "month", money: "range" });
  const [confirmed, setConfirmed] = useState(false);
  // Ansicht merken (nur im Browser; ohne Speicher Standard: Daten, nach Freigabe Chat).
  const [view, setView] = useState<View>(tables.released ? "chat" : "data");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(VIEW_KEY);
      if (saved === "data" || saved === "chat" || saved === "split") setView(saved);
    } catch { /* kein Speicher: Standard */ }
  }, []);
  const choose = (v: View) => {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* egal */ }
  };

  const label = (key: string) => tables.columns.find(c => c.key === key)?.label ?? key;
  const toggle = (key: string) =>
    setSelected(s => (s.includes(key) ? s.filter(k => k !== key) : [...s, key]));

  const run = <T,>(fn: () => Promise<{ ok: true; data: T } | { ok: false; error: string }>, then: (d: T) => void) =>
    start(async () => {
      setError(null);
      setMessage(null);
      const r = await fn();
      if (r.ok) then(r.data);
      else setError(r.error);
    });

  const anonymize = () => run(() => arcaPreview(selected, options), p => { setPreview(p); setConfirmed(false); });
  const release = () => preview && run(() => arcaRelease(preview.id, confirmed), a => {
    setPreview(null);
    setMessage(`Freigegeben: ${a.columns.map(label).join(", ")} · ${a.row_count} Zeilen`);
    router.refresh();
  });
  const revoke = () => run(() => arcaRevoke(), () => {
    setMessage("Freigabe widerrufen. visible.db ist leer.");
    router.refresh();
  });
  const upload = (form: FormData) => run(() => arcaUpload(form), d => {
    setMessage(`${d.dateiname}: ${d.chars} Zeichen${d.ocr ? " per lokalem OCR" : ""} in vault.db gespeichert`);
    router.refresh();
  });
  const visible = tables.visible;
  // Vorschläge für den Chat: einer mit einem Klarnamen aus B, damit die Pseudonymisierung sichtbar wird.
  const firstClient = String(tables.vault[0]?.mandant ?? "").trim();
  const suggestions = [
    "Welche Mandate haben den höchsten Streitwert? Nenne die drei größten.",
    firstClient ? `Fasse das Mandat von ${firstClient} in drei Sätzen zusammen.` : "Fasse das erste Mandat in drei Sätzen zusammen.",
    "Welche Fristen, Termine oder offenen Risiken stehen in den freigegebenen Daten?",
  ];

  return (
    <div className="space-y-4">
    <div role="tablist" aria-label="Ansicht" className="bg-muted inline-flex rounded-lg p-1 text-sm">
      {VIEWS.map(v => (
        <button key={v.key} type="button" role="tab" aria-selected={view === v.key} onClick={() => choose(v.key)}
                className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1",
                  view === v.key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
          <v.icon className="h-4 w-4" aria-hidden />{v.label}
        </button>
      ))}
    </div>
    <div className={cn("grid gap-4", view === "split" && "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] 2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]")}>
     <div className={cn("min-w-0 space-y-4", view === "chat" && "hidden")}>
      <div className="space-y-4">
        <Widget title="B · Vertraulich" description="vault.db · Originaldaten. Spalten anhaken, die nach A sollen.">
          <Grid
            head={tables.columns.map(c => (
              <label key={c.key} className="inline-flex cursor-pointer items-center gap-1">
                <input type="checkbox" checked={selected.includes(c.key)} onChange={() => toggle(c.key)}
                       aria-label={`${c.label} nach A übernehmen`} />
                {c.label}
              </label>
            ))}
            selected={tables.columns.map(c => selected.includes(c.key))}
            rows={tables.vault.map(row => tables.columns.map(c => String(row[c.key] ?? "")))}
            titles={tables.vault.map(row => tables.columns.map(c => String(row[c.key] ?? "")))}
          />
        </Widget>

        <Widget title="A · KI-sichtbar"
                description={preview ? "Vorschau · ersetzte Werte farbig" : "visible.db · das Einzige, was Claude lesen kann"}>
          <div className="mb-2">
            {preview
              ? <span className="bg-light-yellow text-dark-yellow rounded-md px-2 py-0.5 text-xs">nicht freigegeben</span>
              : tables.released
                ? <span className="bg-light-green text-dark-green rounded-md px-2 py-0.5 text-xs">freigegeben</span>
                : <span className="bg-muted text-muted-foreground rounded-md px-2 py-0.5 text-xs">leer</span>}
          </div>
          {preview ? (
            <Grid head={preview.columns.map(label)}
                  rows={preview.rows.map(r => preview.columns.map(c => <Highlighted key={c} {...r.cells[c]!} />))}
                  titles={preview.rows.map(r => preview.columns.map(c => r.cells[c]!.value))} />
          ) : visible.columns.length ? (
            <Grid head={visible.columns.slice(1).map(label)}
                  rows={visible.rows.map(r => r.slice(1).map(v => String(v ?? "")))}
                  titles={visible.rows.map(r => r.slice(1).map(v => String(v ?? "")))} />
          ) : (
            <p className="text-muted-foreground py-8 text-center text-xs">Noch nichts freigegeben. visible.db ist leer.</p>
          )}
        </Widget>
      </div>

      <Widget title="Dokument hinzufügen"
              description={tables.ocr
                ? "PDF, Scan, Bild, DOCX oder Text. Scans liest Tesseract lokal ohne Netzwerkzugang; gespeichert wird nur der Text in vault.db."
                : "Lokales OCR nicht verfügbar (tesseract-ocr-deu und unshare nötig). Scans werden abgelehnt, Text-PDFs und DOCX gehen."}>
        <form action={upload} className="flex flex-wrap items-center gap-2 text-xs">
          <select name="mandat_id" required defaultValue="" className="border-input bg-background h-8 rounded-md border px-2">
            <option value="" disabled>Mandat wählen</option>
            {tables.vault.map(r => <option key={String(r.id)} value={String(r.id)}>{String(r.aktenzeichen)} · {String(r.mandant)}</option>)}
          </select>
          <input type="file" name="file" required accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.docx,.txt,.md" className="text-xs" />
          <Button type="submit" size="sm" variant="outline" disabled={pending}><FileUp className="mr-1 h-3.5 w-3.5" aria-hidden />Hochladen</Button>
          {tables.documents.length > 0 && (
            <span className="text-muted-foreground">
              {tables.documents.length} Dokument(e), davon {tables.documents.filter(d => d.ocr).length} per OCR
            </span>
          )}
        </form>
      </Widget>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="inline-flex items-center gap-1">Daten
          <select value={options.dates} onChange={e => setOptions(o => ({ ...o, dates: e.target.value as ArcaOptions["dates"] }))}
                  className="border-input bg-background h-8 rounded-md border px-2">
            <option value="month">Monat/Jahr</option><option value="year">nur Jahr</option><option value="keep">genau (riskant)</option>
          </select>
        </label>
        <label className="inline-flex items-center gap-1">Beträge
          <select value={options.money} onChange={e => setOptions(o => ({ ...o, money: e.target.value as ArcaOptions["money"] }))}
                  className="border-input bg-background h-8 rounded-md border px-2">
            <option value="range">als Spanne</option><option value="keep">genau (riskant)</option>
          </select>
        </label>
        <Button onClick={anonymize} disabled={pending || !selected.length}>Anonymisieren</Button>
        <Button variant="destructive-secondary" onClick={revoke} disabled={pending || !tables.released}>Freigabe widerrufen</Button>
        {pending && <span className="text-muted-foreground">Läuft …</span>}
        {error && <span role="alert" className="bg-light-red text-dark-red rounded-md px-2 py-0.5">{error}</span>}
        {message && <span className="bg-light-green text-dark-green rounded-md px-2 py-0.5">{message}</span>}
      </div>

      {preview && (
        <Widget title="Prüfung vor der Freigabe"
                description="Pflicht: Vorschau in A vollständig lesen. Gelb unterstrichen = Eigenname, der nicht ersetzt wurde.">
          {preview.hints > 0 ? (
            <p className="bg-light-yellow text-dark-yellow mb-2 rounded-md px-2 py-1 text-xs">
              {preview.hints} Prüfhinweis(e): {[...new Set(preview.rows.flatMap(r => Object.values(r.cells).flatMap(c =>
                c.spans.filter(sp => sp.type === "check").map(sp => c.value.slice(sp.start, sp.end)))))].join(", ")}.
              Ist darunter ein Name oder Ort, der auf die Mandantschaft schließen lässt: nicht freigeben, Spalte abwählen
              oder Text in B anpassen.
            </p>
          ) : (
            <p className="text-muted-foreground mb-2 text-xs">Keine Prüfhinweise. Lies trotzdem: Ortsteile und Umschreibungen erkennt Arca nicht sicher.</p>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="inline-flex cursor-pointer items-center gap-1.5">
              <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
              Ich habe die Vorschau vollständig geprüft; sie lässt keinen Rückschluss auf Mandanten oder Beteiligte zu.
            </label>
            <Button variant="outline-success" onClick={release} disabled={pending || !confirmed}>Freigeben</Button>
            <span className="text-muted-foreground">Wird mit deinem Namen im Audit-Log protokolliert.</span>
          </div>
        </Widget>
      )}

      <Widget title="Audit-Log" description="vault.db · Freigaben, Widerrufe, Uploads und jede Frage an Claude (pseudonymisiert), mit Person">
          <ul className="space-y-1 text-xs">
            {tables.audit.map(e => (
              <li key={e.id} className="flex flex-wrap gap-x-2">
                <span className="text-muted-foreground tabular-nums">{stamp(e.created_at)}</span>
                <span className={ACTIONS[e.action]?.[1] ?? "text-foreground"}>{ACTIONS[e.action]?.[0] ?? e.action}</span>
                {e.action === "chat_message" && typeof e.details?.text === "string" && (
                  <span className="font-mono">{e.details.text.length > 140 ? `${e.details.text.slice(0, 140)} …` : e.details.text}</span>
                )}
                {e.action === "release" && (
                  <span>
                    {e.columns.map(label).join(", ")} · {e.row_count} Zeilen
                    {e.details?.options && ` · Daten ${e.details.options.dates === "keep" ? "genau" : e.details.options.dates === "year" ? "Jahr" : "Monat"}, Beträge ${e.details.options.money === "keep" ? "genau" : "Spanne"}`}
                    {typeof e.details?.hints === "number" && ` · ${e.details.hints} Prüfhinweis(e)`}
                  </span>
                )}
                {e.actor && <span className="text-muted-foreground">· {e.actor}</span>}
              </li>
            ))}
            {!tables.audit.length && <li className="text-muted-foreground">Noch keine Freigabe</li>}
          </ul>
      </Widget>
     </div>

      {/* Der Chat bleibt beim Umschalten eingehängt (nur ausgeblendet), damit das Gespräch erhalten bleibt. */}
      <section aria-label="Claude"
               className={cn("bg-card min-w-0 rounded-xl border py-3",
                 view === "data" && "hidden",
                 view === "chat" && "h-[calc(100vh-11rem)] min-h-[32rem]",
                 view === "split" && "h-[calc(100vh-11rem)] min-h-[32rem] lg:sticky lg:top-4 lg:self-start")}>
        {tables.released ? <Chat url={terminalUrl} suggestions={suggestions} /> : (
          <div className="text-muted-foreground flex h-full min-h-64 flex-col items-center justify-center gap-2 text-sm">
            <Lock className="h-5 w-5" aria-hidden />
            Erst in „Daten“ Spalten anonymisieren und freigeben
          </div>
        )}
      </section>
    </div>
    </div>
  );
}

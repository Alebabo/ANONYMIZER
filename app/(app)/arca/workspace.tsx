"use client";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { FileUp, Lock } from "lucide-react";
import { TableScroll } from "@/components/app-shell";
import { Widget, stamp } from "@/components/widgets";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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

/** Freitext breit und umbrechend, kurze Werte in einer Zeile; die Tabelle scrollt seitlich. */
const cellClass = (key: string) => key === "sachverhalt" || key === "dokumente"
  ? "min-w-[22rem] max-w-[32rem] align-top text-xs whitespace-normal [overflow-wrap:anywhere]"
  : "align-top text-xs whitespace-nowrap";

export function ArcaWorkspace({ tables, terminalUrl }: { tables: ArcaTables; terminalUrl: string }) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<ArcaPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const [options, setOptions] = useState<ArcaOptions>({ dates: "month", money: "range" });
  const [confirmed, setConfirmed] = useState(false);

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
  const short = (key: string, v: string) =>
    key === "dokumente" && v.length > 280 ? `${v.slice(0, 280)} …` : v;
  const visible = tables.visible;
  // Vorschläge für den Chat: einer mit einem Klarnamen aus B, damit die Pseudonymisierung sichtbar wird.
  const firstClient = String(tables.vault[0]?.mandant ?? "").trim();
  const suggestions = [
    "Welche Mandate haben den höchsten Streitwert? Nenne die drei größten.",
    firstClient ? `Fasse das Mandat von ${firstClient} in drei Sätzen zusammen.` : "Fasse das erste Mandat in drei Sätzen zusammen.",
    "Welche Fristen, Termine oder offenen Risiken stehen in den freigegebenen Daten?",
  ];

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] 2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
     <div className="min-w-0 space-y-4">
      <div className="space-y-4">
        <Widget title="B · Vertraulich" description="vault.db · Originaldaten. Spalten anhaken, die nach A sollen.">
          <TableScroll minWidth={0}>
            <Table className="table-auto">
              <TableHeader>
                <TableRow>
                  {tables.columns.map(c => (
                    <TableHead key={c.key} className="text-xs">
                      <label className="inline-flex cursor-pointer items-center gap-1.5">
                        <input type="checkbox" checked={selected.includes(c.key)} onChange={() => toggle(c.key)}
                               aria-label={`${c.label} nach A übernehmen`} />
                        {c.label}
                      </label>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {tables.vault.map(row => (
                  <TableRow key={String(row.id)}>
                    {tables.columns.map(c => (
                      <TableCell key={c.key} className={cn(cellClass(c.key), selected.includes(c.key) && "bg-muted/60")}>
                        {short(c.key, String(row[c.key] ?? ""))}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableScroll>
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
          <TableScroll minWidth={0}>
            {preview ? (
              <Table className="table-auto">
                <TableHeader>
                  <TableRow>{preview.columns.map(c => <TableHead key={c} className="text-xs">{label(c)}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {preview.rows.map(r => (
                    <TableRow key={r.zeile}>
                      {preview.columns.map(c => (
                        <TableCell key={c} className={cellClass(c)}><Highlighted {...r.cells[c]!} /></TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : visible.columns.length ? (
              <Table className="table-auto">
                <TableHeader>
                  <TableRow>{visible.columns.map(c => <TableHead key={c} className="text-xs">{c === "zeile" ? "#" : label(c)}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {visible.rows.map(r => (
                    <TableRow key={String(r[0])}>
                      {r.map((v, i) => <TableCell key={i} className={cellClass(visible.columns[i]!)}>{String(v ?? "")}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-muted-foreground py-8 text-center text-xs">Noch nichts freigegeben. visible.db ist leer.</p>
            )}
          </TableScroll>
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

      <Widget title="Claude" className="lg:sticky lg:top-4 lg:h-[calc(100vh-9rem)] lg:self-start"
              description="Eigenes Claude-Abo. Fragen werden vor dem Senden pseudonymisiert; sichtbar ist, was an Claude geht und welche Abfragen Claude auf A macht.">
        {tables.released ? <Chat url={terminalUrl} suggestions={suggestions} /> : (
          <div className="bg-muted text-muted-foreground flex h-64 flex-col items-center justify-center gap-2 rounded-md text-sm">
            <Lock className="h-5 w-5" aria-hidden />
            Erst Spalten anonymisieren und freigeben
          </div>
        )}
      </Widget>
    </div>
  );
}

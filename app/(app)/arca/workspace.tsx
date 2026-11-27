"use client";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { FileUp, Lock } from "lucide-react";
import { TableScroll } from "@/components/app-shell";
import { Widget, stamp } from "@/components/widgets";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ArcaCell, ArcaPreview, ArcaSpan, ArcaTables } from "@/lib/arca-api";
import { cn } from "@/lib/utils";
import { arcaPreview, arcaRelease, arcaRetranslate, arcaRevoke, arcaUpload } from "./actions";
import type { TerminalHandle } from "./terminal";

const Terminal = dynamic(() => import("./terminal").then(m => m.Terminal), { ssr: false });

const typeStyle: Record<string, string> = {
  person: "bg-light-blue text-dark-blue",
  organization: "bg-light-violet text-dark-violet",
  location: "bg-light-teal text-dark-teal",
  address: "bg-light-teal text-dark-teal",
  case_number: "bg-light-yellow text-dark-yellow",
  withheld: "bg-light-red text-dark-red",
};
const mark = (type: string) => cn("rounded-sm px-0.5", typeStyle[type] ?? "bg-light-green text-dark-green");

/** Wert mit farbig hervorgehobenen Ersetzungen. */
function Highlighted({ value, spans }: { value: string; spans: ArcaSpan[] }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  [...spans].sort((a, b) => a.start - b.start).forEach((s, i) => {
    if (s.start < cursor) return;
    parts.push(value.slice(cursor, s.start));
    parts.push(<mark key={i} title={s.type} className={mark(s.type)}>{value.slice(s.start, s.end)}</mark>);
    cursor = s.end;
  });
  parts.push(value.slice(cursor));
  return <>{parts}</>;
}

/** Freitext breit und umbrechend, kurze Werte in einer Zeile; die Tabelle scrollt seitlich. */
const cellClass = (key: string) => key === "sachverhalt" || key === "dokumente"
  ? "min-w-[22rem] max-w-[32rem] align-top text-xs whitespace-normal [overflow-wrap:anywhere]"
  : "align-top text-xs whitespace-nowrap";

export function ArcaWorkspace({ tables }: { tables: ArcaTables }) {
  const router = useRouter();
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<ArcaPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const terminal = useRef<TerminalHandle | null>(null);
  const [answer, setAnswer] = useState("");
  const [translated, setTranslated] = useState<ArcaCell | null>(null);

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

  const anonymize = () => run(() => arcaPreview(selected), p => setPreview(p));
  const release = () => preview && run(() => arcaRelease(preview.id), a => {
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
  const retranslate = () => run(() => arcaRetranslate(answer), r =>
    setTranslated({ value: r.text, spans: r.spans.map(s => ({ start: s.start, end: s.end, type: "person" })) }));

  const visible = tables.visible;
  return (
    <>
      <div className="grid gap-4 xl:grid-cols-2">
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

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={anonymize} disabled={pending || !selected.length}>Anonymisieren</Button>
        <Button variant="outline-success" onClick={release} disabled={pending || !preview}>Freigeben</Button>
        <Button variant="destructive-secondary" onClick={revoke} disabled={pending || !tables.released}>Freigabe widerrufen</Button>
        {pending && <span className="text-muted-foreground text-xs">Läuft …</span>}
        {error && <span role="alert" className="bg-light-red text-dark-red rounded-md px-2 py-0.5 text-xs">{error}</span>}
        {message && <span className="bg-light-green text-dark-green rounded-md px-2 py-0.5 text-xs">{message}</span>}
      </div>

      <Widget title="Claude" description="claude-CLI · einziger Datenzugang: Arca-MCP (nur visible.db, nur SELECT), keine Built-in-Tools">
        {tables.released ? (
          <Terminal ref={terminal} />
        ) : (
          <div className="bg-muted text-muted-foreground flex h-64 flex-col items-center justify-center gap-2 rounded-md text-sm">
            <Lock className="h-5 w-5" aria-hidden />
            Erst freigeben
          </div>
        )}
      </Widget>

      <div className="grid gap-4 xl:grid-cols-2">
        <Widget title="Zurückübersetzen" description="Claude-Antwort lokal mit Klarnamen anzeigen. Nur hier in der UI, nie zurück an Claude.">
          <textarea value={answer} onChange={e => setAnswer(e.target.value)} rows={4}
                    placeholder="Antwort von Claude einfügen oder im Terminal markieren"
                    className="border-input bg-background w-full rounded-md border p-2 font-mono text-xs" />
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="outline" disabled={!tables.released}
                    onClick={() => setAnswer(terminal.current?.selection() ?? "")}>Terminal-Auswahl übernehmen</Button>
            <Button size="sm" onClick={retranslate} disabled={pending || !answer.trim()}>Zurückübersetzen</Button>
          </div>
          {translated && (
            <p className="bg-muted mt-3 rounded-md p-2 text-xs whitespace-pre-wrap"><Highlighted {...translated} /></p>
          )}
        </Widget>

        <Widget title="Audit-Log" description="vault.db · jede Freigabe und jeder Widerruf">
          <ul className="space-y-1 text-xs">
            {tables.audit.map(e => (
              <li key={e.id} className="flex gap-2">
                <span className="text-muted-foreground tabular-nums">{stamp(e.created_at)}</span>
                <span className={e.action === "release" ? "text-dark-green" : e.action === "revoke" ? "text-dark-red" : "text-dark-blue"}>
                  {e.action === "release" ? "Freigabe" : e.action === "revoke" ? "Widerruf" : "Dokument (nur vault.db)"}
                </span>
                {e.action === "release" && <span>{e.columns.map(label).join(", ")} · {e.row_count} Zeilen</span>}
              </li>
            ))}
            {!tables.audit.length && <li className="text-muted-foreground">Noch keine Freigabe</li>}
          </ul>
        </Widget>
      </div>
    </>
  );
}

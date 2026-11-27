"use client";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { FileUp, Lock, Send, ShieldAlert, ShieldCheck } from "lucide-react";
import { TableScroll } from "@/components/app-shell";
import { Widget, stamp } from "@/components/widgets";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ArcaCell, ArcaOptions, ArcaPreview, ArcaSpan, ArcaTables } from "@/lib/arca-api";
import { cn } from "@/lib/utils";
import { arcaPreview, arcaPseudonymize, arcaRelease, arcaRetranslate, arcaRevoke, arcaUpload } from "./actions";
import type { TerminalEvent, TerminalHandle } from "./terminal";

const Terminal = dynamic(() => import("./terminal").then(m => m.Terminal), { ssr: false });

const typeStyle: Record<string, string> = {
  person: "bg-light-blue text-dark-blue",
  organization: "bg-light-violet text-dark-violet",
  location: "bg-light-teal text-dark-teal",
  address: "bg-light-teal text-dark-teal",
  case_number: "bg-light-yellow text-dark-yellow",
  withheld: "bg-light-red text-dark-red",
  date: "bg-muted text-foreground-secondary",
  money: "bg-muted text-foreground-secondary",
  // Prüfhinweis: nicht ersetzt, bitte ansehen
  check: "bg-light-yellow text-dark-yellow underline decoration-dotted underline-offset-2",
};
const typeTitle: Record<string, string> = {
  date: "Datum vergröbert", money: "Betrag als Spanne", check: "Prüfhinweis: Eigenname nicht ersetzt",
};

const ACTIONS: Record<string, [string, string]> = {
  release: ["Freigabe", "text-dark-green"], revoke: ["Widerruf", "text-dark-red"],
  document: ["Dokument (nur vault.db)", "text-dark-blue"],
  terminal_unlock: ["Direkteingabe freigeschaltet", "text-dark-red"], terminal_lock: ["Direkteingabe gesperrt", "text-dark-green"],
};
const mark = (type: string) => cn("rounded-sm px-0.5", typeStyle[type] ?? "bg-light-green text-dark-green");

/** Wert mit farbig hervorgehobenen Ersetzungen. */
function Highlighted({ value, spans }: { value: string; spans: ArcaSpan[] }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  [...spans].sort((a, b) => a.start - b.start).forEach((s, i) => {
    if (s.start < cursor) return;
    parts.push(value.slice(cursor, s.start));
    parts.push(<mark key={i} title={typeTitle[s.type] ?? s.type} className={mark(s.type)}>{value.slice(s.start, s.end)}</mark>);
    cursor = s.end;
  });
  parts.push(value.slice(cursor));
  return <>{parts}</>;
}

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
  const terminal = useRef<TerminalHandle | null>(null);
  const [answer, setAnswer] = useState("");
  const [translated, setTranslated] = useState<ArcaCell | null>(null);
  const [options, setOptions] = useState<ArcaOptions>({ dates: "month", money: "range" });
  const [confirmed, setConfirmed] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [checked, setChecked] = useState<{ source: string; text: string; spans: ArcaSpan[]; hints: string[] } | null>(null);
  const [mode, setMode] = useState<"protected" | "direct">("protected");
  const [termNote, setTermNote] = useState<string | null>(null);
  const [sent, setSent] = useState<string[]>([]);
  const [login, setLogin] = useState<{ url: string | null } | null>(null);
  const [authCode, setAuthCode] = useState("");

  const onTerminal = (e: TerminalEvent) => {
    if ("mode" in e) setMode(e.mode);
    else if ("blocked" in e) setTermNote(e.login
      ? "Login-Code bitte oben im Feld \"Claude-Anmeldung\" einfügen."
      : "Direkteingabe gesperrt: Frage unten eingeben, sie wird vor dem Senden pseudonymisiert.");
    else if ("login" in e) {
      setLogin(e.login ? { url: e.url ?? null } : null);
      setTermNote(e.login ? null : "Login-Code gesendet.");
    }
    else if ("sent" in e) {
      setSent(s => [e.sent, ...s].slice(0, 5));
      setTermNote(e.hints.length ? `Gesendet. Prüfhinweise: ${e.hints.join(", ")}` : "Gesendet (pseudonymisiert).");
    } else if ("error" in e) setTermNote(e.error);
  };
  const checkPrompt = () => run(() => arcaPseudonymize(prompt), r => setChecked({ source: prompt, ...r }));
  const sendPrompt = () => {
    if (!checked || checked.source !== prompt) return;
    terminal.current?.sendPrompt(prompt);
    setPrompt("");
    setChecked(null);
  };
  const toggleDirect = () => {
    if (mode === "direct") terminal.current?.lock();
    else if (window.confirm("Direkteingabe freischalten? Alles, was du tippst oder einfügst, geht dann UNGEFILTERT an Claude. "
      + "Nur für Ausnahmen (die Anmeldung geht über das Anmeldefeld), nie für Mandatsinhalte. Das Freischalten wird mit deinem Namen protokolliert.")) {
      terminal.current?.unlock();
    }
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

      <Widget title="Claude" description="claude-CLI mit deinem eigenen Claude-Abo (beim ersten Start anmelden) · einziger Datenzugang: Arca-MCP (nur visible.db, nur SELECT), keine Built-in-Tools">
        {tables.released ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {mode === "protected" ? (
                <span className="bg-light-green text-dark-green inline-flex items-center gap-1 rounded-md px-2 py-0.5">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden />Geschützt: Fragen nur über das Feld unten (pseudonymisiert)
                </span>
              ) : (
                <span className="bg-light-red text-dark-red inline-flex items-center gap-1 rounded-md px-2 py-0.5">
                  <ShieldAlert className="h-3.5 w-3.5" aria-hidden />Direkteingabe offen: Getipptes geht ungefiltert an Claude
                </span>
              )}
              <Button size="sm" variant={mode === "direct" ? "outline-success" : "destructive-secondary"} onClick={toggleDirect}>
                {mode === "direct" ? "Direkteingabe sperren" : "Direkteingabe freischalten (Ausnahme)"}
              </Button>
              {termNote && <span className="text-muted-foreground">{termNote}</span>}
            </div>
            {login && (
              <div className="border-dark-blue bg-light-blue/40 space-y-2 rounded-md border p-3 text-xs">
                <p className="font-medium">Claude-Anmeldung (einmalig, mit deinem eigenen Claude-Konto)</p>
                <p>
                  1.{" "}
                  {login.url
                    ? <a href={login.url} target="_blank" rel="noopener noreferrer" className="text-link hover:text-link-hover underline">Anmeldeseite öffnen</a>
                    : "Den Link im Terminal anklicken"}
                  , anmelden und den angezeigten Code kopieren.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <span>2.</span>
                  <input value={authCode} onChange={e => setAuthCode(e.target.value)} placeholder="Code hier einfügen"
                         autoComplete="off" spellCheck={false}
                         className="border-input bg-background h-8 min-w-[18rem] flex-1 rounded-md border px-2 font-mono" />
                  <Button size="sm" disabled={authCode.trim().length < 20 || /\s/.test(authCode.trim())}
                          onClick={() => { terminal.current?.sendAuthCode(authCode); setAuthCode(""); }}>Code senden</Button>
                </div>
                <p className="text-muted-foreground">
                  Du kannst den Code auch direkt ins Terminal einfügen (Strg+V). Durch geht nur ein Code ohne Leerzeichen;
                  Freitext bleibt gesperrt. Die Anmeldung bleibt für dich gespeichert.
                </p>
              </div>
            )}
            <Terminal ref={terminal} url={terminalUrl} onEvent={onTerminal} />
            <div className="space-y-2">
              <textarea value={prompt} onChange={e => { setPrompt(e.target.value); }} rows={3}
                        placeholder="Frage an Claude, gern mit Klarnamen: wird vor dem Senden mit denselben Tokens wie in A pseudonymisiert"
                        className="border-input bg-background w-full rounded-md border p-2 text-sm" />
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={checkPrompt} disabled={pending || !prompt.trim()}>Prüfen</Button>
                <Button size="sm" onClick={sendPrompt} disabled={!checked || checked.source !== prompt}>
                  <Send className="mr-1 h-3.5 w-3.5" aria-hidden />An Claude senden
                </Button>
                {checked && checked.source !== prompt && <span className="text-muted-foreground text-xs">Text geändert: erneut prüfen</span>}
              </div>
              {checked && checked.source === prompt && (
                <p className="bg-muted rounded-md p-2 text-xs whitespace-pre-wrap">
                  <span className="text-muted-foreground">Claude bekommt: </span><Highlighted value={checked.text} spans={checked.spans} />
                </p>
              )}
              {sent.length > 0 && (
                <details className="text-xs">
                  <summary className="text-muted-foreground cursor-pointer">Zuletzt gesendet ({sent.length})</summary>
                  <ul className="mt-1 space-y-1 font-mono">{sent.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </details>
              )}
            </div>
          </div>
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

        <Widget title="Audit-Log" description="vault.db · Freigaben, Widerrufe, Uploads und Direkteingabe, mit Person">
          <ul className="space-y-1 text-xs">
            {tables.audit.map(e => (
              <li key={e.id} className="flex flex-wrap gap-x-2">
                <span className="text-muted-foreground tabular-nums">{stamp(e.created_at)}</span>
                <span className={ACTIONS[e.action]?.[1] ?? "text-foreground"}>{ACTIONS[e.action]?.[0] ?? e.action}</span>
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
    </>
  );
}

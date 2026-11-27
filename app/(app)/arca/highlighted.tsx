import type { ArcaSpan } from "@/lib/arca-api";
import { cn } from "@/lib/utils";

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
  // Zurückübersetzt (nur lokal angezeigt)
  restored: "bg-light-green text-dark-green",
};
const typeTitle: Record<string, string> = {
  date: "Datum vergröbert", money: "Betrag als Spanne", check: "Prüfhinweis: Eigenname nicht ersetzt",
  restored: "Klarname, nur hier lokal angezeigt",
};
const mark = (type: string) => cn("rounded-sm px-0.5", typeStyle[type] ?? "bg-light-green text-dark-green");

/** Wert mit farbig hervorgehobenen Ersetzungen. Mit ``markdown``: **fett** und `Code` (Claude-Antworten). */
export function Highlighted({ value, spans, markdown = false }: { value: string; spans: ArcaSpan[]; markdown?: boolean }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  // Fett/Code nur im Text zwischen den Markierungen; Marker (** und `) werden ausgeblendet, Offsets bleiben gültig.
  const plain = (text: string) => {
    if (!markdown) return parts.push(text);
    for (const piece of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/)) {
      if (!piece) continue;
      if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) parts.push(<strong key={key++}>{piece.slice(2, -2)}</strong>);
      else if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 2) parts.push(<code key={key++} className="bg-background rounded px-1 font-mono text-[0.9em]">{piece.slice(1, -1)}</code>);
      else parts.push(piece.replace(/\*\*/g, ""));
    }
  };
  [...spans].sort((a, b) => a.start - b.start).forEach(s => {
    if (s.start < cursor) return;
    plain(value.slice(cursor, s.start));
    parts.push(<mark key={key++} title={typeTitle[s.type] ?? s.type} className={mark(s.type)}>{value.slice(s.start, s.end)}</mark>);
    cursor = s.end;
  });
  plain(value.slice(cursor));
  return <>{parts}</>;
}

/** Tokens wie PERSON_1a2b3c4d im Text farbig markieren (ohne Spans vom Server). */
const TOKEN = /\b[A-Z]+(?:_[A-Z]+)*_[0-9a-f]{8}\b/g;
export function tokenSpans(text: string): ArcaSpan[] {
  return [...text.matchAll(TOKEN)].map(m => {
    const kind = m[0].replace(/_[0-9a-f]{8}$/, "").toLowerCase();
    return { start: m.index!, end: m.index! + m[0].length, type: kind };
  });
}

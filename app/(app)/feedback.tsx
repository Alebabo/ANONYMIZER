"use client";
import { useRef, useState, useTransition } from "react";
import { Check, X } from "lucide-react";
import { sendFeedback, type Detected, type FeedbackSpan } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Types a correction can name; the value is the API type. */
export const FEEDBACK_TYPES: [string, string][] = [
  ["person", "Name"], ["organization", "Company / organisation"], ["location", "Place"], ["address", "Address"],
  ["case_number", "Case number"], ["court", "Court"], ["legal_citation", "Statute / citation"], ["date", "Date"],
  ["iban", "IBAN"], ["email", "E-mail"], ["phone", "Phone"], ["other", "Other"],
];
const typeLabel = (t: string) => FEEDBACK_TYPES.find(([v]) => v === t)?.[1] ?? t;

/** Character offset of a DOM position inside `root` (the text is rendered unchanged, so offsets match). */
function offsetIn(root: HTMLElement, node: Node, offset: number) {
  const r = document.createRange();
  r.setStart(root, 0);
  r.setEnd(node, offset);
  return r.toString().length;
}

type Segment = { start: number; end: number; det?: Detected; mark?: FeedbackSpan };

function segments(text: string, dets: Detected[], marks: FeedbackSpan[]): Segment[] {
  const cuts = new Set([0, text.length]);
  for (const x of [...dets, ...marks]) { cuts.add(x.start); cuts.add(x.end); }
  const pts = [...cuts].filter(n => n >= 0 && n <= text.length).sort((a, b) => a - b);
  return pts.slice(0, -1).map((start, i) => {
    const end = pts[i + 1]!;
    return { start, end, det: dets.find(d => d.start <= start && end <= d.end),
             mark: marks.find(m => m.start <= start && end <= m.end) };
  });
}

/**
 * Correct one chat message: select text that should have been found and pick a type, or click a
 * found value (underlined) that is not personal data. Saved with the text for training.
 */
export function Feedback({ text, detections, policy, traceId, onClose }: {
  text: string; detections: Detected[]; policy: string; traceId: string | null; onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [marks, setMarks] = useState<FeedbackSpan[]>([]);
  const [sel, setSel] = useState<{ start: number; end: number } | null>(null);
  const [type, setType] = useState("person");
  const [state, setState] = useState<{ ok?: boolean; error?: string; message?: string }>({});
  const [pending, start] = useTransition();

  const onSelect = () => {
    const s = window.getSelection();
    if (!s || s.isCollapsed || !box.current || !box.current.contains(s.anchorNode) || !box.current.contains(s.focusNode)) return;
    const r = s.getRangeAt(0);
    let a = offsetIn(box.current, r.startContainer, r.startOffset);
    let b = offsetIn(box.current, r.endContainer, r.endOffset);
    while (a < b && /\s/.test(text[a]!)) a++;           // trim spaces the mouse picked up
    while (b > a && /[\s.,;:!?)]/.test(text[b - 1]!)) b--;
    setSel(b > a ? { start: a, end: b } : null);
  };

  const toggleWrong = (d: Detected) => setMarks(ms => ms.some(m => m.kind === "wrong" && m.start === d.start && m.end === d.end)
    ? ms.filter(m => !(m.kind === "wrong" && m.start === d.start && m.end === d.end))
    : [...ms, { start: d.start, end: d.end, kind: "wrong", label: d.type }]);

  const addMissed = () => {
    if (!sel) return;
    setMarks(ms => [...ms.filter(m => m.end <= sel.start || m.start >= sel.end), { ...sel, kind: "missed", label: type }]);
    setSel(null);
    window.getSelection()?.removeAllRanges();
  };

  const save = () => start(async () => {
    const r = await sendFeedback(text, marks, policy, traceId).catch(() => ({ error: "Request failed." }));
    setState(r);
    if ("ok" in r && r.ok) setMarks([]);
  });

  return (
    <div className="bg-card space-y-2 rounded-lg border p-3 text-sm">
      <div className="text-muted-foreground text-xs">
        Select text that should have been found, or click an underlined value that is not personal data.
        Saved with the text for training: <b>test data only</b>.
      </div>
      <div ref={box} onMouseUp={onSelect} onKeyUp={onSelect}
           className="bg-background rounded-md border px-3 py-2 leading-7 whitespace-pre-wrap break-words select-text">
        {segments(text, detections, marks).map(s => {
          const t = text.slice(s.start, s.end);
          if (s.mark?.kind === "missed")
            return <mark key={s.start} title={`should be: ${typeLabel(s.mark.label)}`} className="bg-light-yellow text-dark-yellow rounded-sm">{t}</mark>;
          if (s.det) {
            const wrong = s.mark?.kind === "wrong";
            return (
              <button key={s.start} type="button" onClick={() => toggleWrong(s.det!)}
                      title={wrong ? "marked: not personal data (click to undo)" : `found: ${s.det.type} (click if wrong)`}
                      className={cn("rounded-sm underline decoration-2 underline-offset-4",
                        wrong ? "bg-light-red text-dark-red line-through" : "decoration-dark-green hover:bg-muted")}>
                {t}
              </button>
            );
          }
          return <span key={s.start}>{t}</span>;
        })}
      </div>

      {sel && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="bg-muted max-w-48 truncate rounded px-1.5 py-0.5 font-mono">{text.slice(sel.start, sel.end)}</span>
          <span className="text-muted-foreground">should be found as</span>
          <select value={type} onChange={e => setType(e.target.value)} className="border-input bg-background h-7 rounded-md border px-1.5">
            {FEEDBACK_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <Button type="button" size="sm" variant="outline" onClick={addMissed}><Check className="h-3.5 w-3.5" />Add</Button>
        </div>
      )}

      {marks.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 text-xs">
          {marks.map(m => (
            <li key={`${m.kind}${m.start}`} className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5",
              m.kind === "missed" ? "bg-light-yellow text-dark-yellow" : "bg-light-red text-dark-red")}>
              <span className="max-w-40 truncate">{text.slice(m.start, m.end)}</span>
              <span>→ {m.kind === "missed" ? typeLabel(m.label) : "not personal data"}</span>
              <button type="button" aria-label="Remove" onClick={() => setMarks(ms => ms.filter(x => x !== m))}><X className="h-3 w-3" /></button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" disabled={!marks.length || pending} onClick={save}>Save feedback</Button>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>Close</Button>
        {state.error && <span role="alert" className="text-dark-red text-xs">{state.error}</span>}
        {state.message && <span role="status" className="text-dark-green text-xs">{state.message}</span>}
      </div>
    </div>
  );
}

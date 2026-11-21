"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { ArrowUp, Trash2 } from "lucide-react";
import { protectText, type ChatResult } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/widgets";
import { Feedback } from "./feedback";
import { cn } from "@/lib/utils";

type Turn = { id: number; input: string; policy: string; result?: ChatResult };

// Placeholders and removed values in the output, highlighted so the change is visible at a glance.
const MARK = /(\b[A-Z][A-Z_]*_\d{3}\b|\[(?:REDACTED|WITHHELD)\]|\*{2,})/g;

function Highlighted({ text }: { text: string }) {
  return <>{text.split(MARK).map((part, i) => (i % 2
    ? <mark key={i} className="bg-light-green text-dark-green rounded-sm px-0.5">{part}</mark>
    : <span key={i}>{part}</span>))}</>;
}

/** "health_data (det_f471c2df3296) → local_only" twice -> "health_data → local_only": no internal ids, no repeats. */
const reasons = (rs: string[]) => [...new Set(rs.map(x => x.replace(/\s*\(det_[0-9a-f]+\)/g, "")))];

function Answer({ r, onCorrect }: { r?: ChatResult; onCorrect?: () => void }) {
  if (!r) return <div className="text-muted-foreground animate-pulse text-sm">Anonymizing…</div>;
  if ("error" in r) return <div className="bg-light-red text-dark-red rounded-md px-3 py-2 text-sm">{r.error}</div>;
  return (
    <div className="space-y-2">
      {r.text != null ? (
        <pre className="bg-card rounded-md border px-3 py-2 font-sans text-sm whitespace-pre-wrap break-words"><Highlighted text={r.text} /></pre>
      ) : (
        <div className="bg-light-red text-dark-red rounded-md px-3 py-2 text-sm">
          Not sent ({r.outcome}){r.reasons.length ? `: ${reasons(r.reasons).join("; ")}` : ""}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Chip>{r.outcome}</Chip>
        {Object.entries(r.entities).sort((a, b) => b[1] - a[1]).map(([k, n]) => <Chip key={k}>{k} {n}</Chip>)}
        {!Object.keys(r.entities).length && <span className="text-muted-foreground">nothing personal found</span>}
        <span className="text-muted-foreground ml-auto">{r.policy}</span>
        {onCorrect && <button type="button" onClick={onCorrect} className="text-link hover:text-link-hover">Correct detection</button>}
        {r.trace_id && <Link href={`/traces/${r.trace_id}`} className="text-link hover:text-link-hover">Trace →</Link>}
      </div>
    </div>
  );
}

/** Type a text, get back what the model would receive. Each message is one traced call (client "dashboard"). */
export function Chat({ policies, defaultPolicy }: { policies: string[]; defaultPolicy: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [correcting, setCorrecting] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [policy, setPolicy] = useState(defaultPolicy);
  const [pending, start] = useTransition();
  const end = useRef<HTMLDivElement>(null);
  const next = useRef(1);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns]);

  const send = () => {
    const input = text.trim();
    if (!input || pending) return;
    const id = next.current++;
    setTurns(t => [...t, { id, input, policy }]);
    setText("");
    start(async () => {
      const result = await protectText(input, policy).catch(() => ({ error: "Request failed." }));
      setTurns(t => t.map(x => (x.id === id ? { ...x, result } : x)));
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-auto px-4 py-4 md:px-6">
        {!turns.length && (
          <div className="text-muted-foreground mx-auto max-w-md pt-16 text-center text-sm">
            Paste or type a text. You get back exactly what an AI model would receive with the chosen policy.
          </div>
        )}
        {turns.map(t => (
          <div key={t.id} className="mx-auto max-w-3xl space-y-2">
            <div className="bg-muted ml-auto w-fit max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words">{t.input}</div>
            <div className="max-w-[85%]">
              <Answer r={t.result} onCorrect={t.result && !("error" in t.result) ? () => setCorrecting(t.id) : undefined} />
            </div>
            {correcting === t.id && t.result && !("error" in t.result) && (
              <Feedback text={t.input} detections={t.result.detections} policy={t.policy} traceId={t.result.trace_id}
                        onClose={() => setCorrecting(null)} />
            )}
          </div>
        ))}
        <div ref={end} />
      </div>

      <form onSubmit={e => { e.preventDefault(); send(); }} className="bg-background border-t px-4 py-3 md:px-6">
        <div className="mx-auto max-w-3xl space-y-2">
          <div className="border-input bg-card focus-within:border-border-contrast flex items-end gap-2 rounded-lg border p-2">
            <textarea value={text} onChange={e => setText(e.target.value)} rows={2} autoFocus aria-label="Text"
                      placeholder="e.g. Herr Max Mustermann (max@example.org, IBAN DE89 3704 0044 0532 0130 00) bittet um Rückruf."
                      onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
                      className="max-h-48 min-h-10 flex-1 resize-y bg-transparent px-1 text-sm outline-none" />
            <Button type="submit" size="sm" disabled={!text.trim() || pending} aria-label="Anonymize">
              <ArrowUp className="h-4 w-4" />
            </Button>
          </div>
          <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
            <label className="flex items-center gap-1.5">Policy
              <select value={policy} onChange={e => setPolicy(e.target.value)}
                      className="border-input bg-background h-7 rounded-md border px-1.5 text-xs">
                {policies.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <span>Enter to send · Shift+Enter for a new line</span>
            {turns.length > 0 && (
              <button type="button" onClick={() => setTurns([])} className={cn("hover:text-foreground ml-auto inline-flex items-center gap-1")}>
                <Trash2 className="h-3 w-3" />Clear
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}

import { Download } from "lucide-react";
import { deleteFeedback } from "@/app/actions";
import { SourceBanner, ago } from "@/components/dashboard";
import { InlineAction } from "@/components/forms";
import { Collapsible } from "@/components/widgets";
import { getFeedback, type FeedbackRow } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

/** The text with its corrections: yellow = should have been found (with type), red = found wrongly. */
function Marked({ f }: { f: FeedbackRow }) {
  const out: React.ReactNode[] = [];
  let pos = 0;
  for (const s of [...f.spans].sort((a, b) => a.start - b.start)) {
    if (s.start < pos) continue;
    out.push(<span key={`t${pos}`}>{f.text.slice(pos, s.start)}</span>);
    out.push(
      <mark key={s.start} title={s.kind === "missed" ? `should be ${s.label}` : `wrongly found as ${s.label}`}
            className={cn("rounded-sm px-0.5", s.kind === "missed" ? "bg-light-yellow text-dark-yellow" : "bg-light-red text-dark-red line-through")}>
        {f.text.slice(s.start, s.end)}<sup className="ml-0.5 text-2xs no-underline">{s.kind === "missed" ? s.label : "no"}</sup>
      </mark>);
    pos = s.end;
  }
  out.push(<span key="rest">{f.text.slice(pos)}</span>);
  return <p className="text-sm leading-7 whitespace-pre-wrap break-words">{out}</p>;
}

export default async function FeedbackPage() {
  const { data: rows, source } = await getFeedback();
  return (
    <>
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        {rows === null ? (
          <p className="text-muted-foreground text-sm">Only admins can see feedback, because it contains the original text.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-muted-foreground text-sm">
                {rows.length} correction(s) from the Chat tab. Yellow: should have been found. Red: found, but not personal data.
              </p>
              {rows.length > 0 && (
                <a href="/api/feedback-export" className="text-link hover:text-link-hover ml-auto inline-flex items-center gap-1 text-sm">
                  <Download className="h-3.5 w-3.5" />Export for training (JSONL)
                </a>
              )}
            </div>
            <ul className="space-y-3">
              {rows.map(f => (
                <li key={f.id} className="bg-card rounded-lg border p-3">
                  <Marked f={f} />
                  <div className="text-muted-foreground mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <span>{ago(f.created_at)} · {f.created_by ?? "–"}{f.policy ? ` · ${f.policy}` : ""}</span>
                    <span className="ml-auto"><InlineAction action={deleteFeedback} fields={{ id: f.id }} label="Delete" variant="ghost"
                                                            confirm="Delete this correction and its text?" /></span>
                  </div>
                </li>
              ))}
              {!rows.length && <li className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
                No feedback yet. In the Chat, click “Correct detection” under an answer.</li>}
            </ul>
            <Collapsible title="How feedback is used">
              <p className="text-muted-foreground text-xs">
                The export is the training format of <code>ner_train.py --feedback feedback.jsonl</code>: marked names,
                companies and places are taught as entities, wrong hits as “not an entity”. Case numbers, courts and
                citations are rule types; they show which rules to extend. Feedback stores the original text, is
                visible to admins only and is never part of traces. Creating, exporting and deleting is audited.
              </p>
            </Collapsible>
          </>
        )}
      </div>
    </>
  );
}

import { cn } from "@/lib/utils";
import { wordDiff } from "@/lib/word-diff";

export const delClass = "bg-light-red text-dark-red rounded-sm px-0.5 line-through decoration-1";
export const insClass = "bg-light-green text-dark-green rounded-sm px-0.5 no-underline";

/**
 * The original text with only the changed spots marked: removed in red (struck through), what is sent
 * instead right after it in green. `titles` maps a replacement (e.g. PERSON_001) to a hover text.
 */
export function InlineDiff({ before, after, titles }: { before: string; after: string | null; titles?: Map<string, string> }) {
  if (after == null) return <><del className={delClass}>{before || "∅"}</del> <ins className={insClass}>[WITHHELD]</ins></>;
  if (before === after) return <>{before}</>;
  return <>{wordDiff(before, after).map((p, i) =>
    p.kind === "same" ? <span key={i}>{p.text}</span>
      : p.kind === "del" ? <del key={i} className={delClass}>{p.text}</del>
        : <ins key={i} title={titles?.get(p.text.trim())} className={cn(insClass, "ml-0.5")}>{p.text}</ins>,
  )}</>;
}

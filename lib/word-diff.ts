// Words and whitespace; trailing punctuation is its own token, so "Krüger," keeps the comma when the name is replaced.
const tokens = (s: string) => s.match(/\s+|[^\s]+?(?=[.,;:!?)\]]*(?:\s|$))|[.,;:!?)\]]+/g) ?? [];

export type Part = { kind: "same" | "del" | "ins"; text: string };

/** Word-level diff (LCS). Above ~2M token pairs it falls back to "all removed, all added". */
export function wordDiff(a: string, b: string): Part[] {
  const x = tokens(a), y = tokens(b);
  if (x.length * y.length > 2_000_000) return [{ kind: "del", text: a }, { kind: "ins", text: b }];
  const n = x.length, m = y.length;
  const lcs = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      lcs[i]![j] = x[i] === y[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
  const out: Part[] = [];
  const push = (kind: Part["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last?.kind === kind) last.text += text; else out.push({ kind, text });
  };
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && x[i] === y[j]) { push("same", x[i]!); i++; j++; }
    else if (j < m && (i === n || lcs[i]![j + 1]! >= lcs[i + 1]![j]!)) push("ins", y[j++]!);
    else push("del", x[i++]!);
  }
  // Changes separated only by whitespace form one block ("Tobias Krüger" -> "PERSON_005"): the whole
  // removal first, then the whole replacement.
  const merged: Part[] = [];
  const change = (p?: Part) => p?.kind === "del" || p?.kind === "ins";
  for (let k = 0; k < out.length; k++) {
    if (!change(out[k])) { merged.push(out[k]!); continue; }
    let removed = "", added = "";
    for (; k < out.length; k++) {
      const p = out[k]!;
      if (p.kind === "del") removed += p.text;
      else if (p.kind === "ins") added += p.text;
      else if (!p.text.trim() && change(out[k + 1])) { removed += removed ? p.text : ""; added += added ? p.text : ""; }
      else break;
    }
    k--;
    if (removed.trim()) merged.push({ kind: "del", text: removed.trimEnd() });
    if (added.trim()) merged.push({ kind: "ins", text: added.trimEnd() });
    // Whitespace at the block's end belongs between it and the next word: keep what is actually sent.
    const tail = (added.trim() ? added : removed).match(/\s+$/)?.[0];
    if (tail) merged.push({ kind: "same", text: tail });
  }
  return merged;
}


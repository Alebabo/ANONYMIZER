import { Bot, KeyRound, User, UserX } from "lucide-react";
import type { AuditEntry } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

const NOISE = new Set(["created_at", "created_by", "org_id", "id"]);
const isObj = (v: unknown): v is Record<string, unknown> => Boolean(v) && typeof v === "object" && !Array.isArray(v);

/** Fields worth showing in the table: on updates only what changed, otherwise without bookkeeping fields. */
function salient(value: unknown, other: unknown): unknown {
  if (!isObj(value)) return value;
  const keys = Object.keys(value).filter(k =>
    isObj(other) ? JSON.stringify(value[k]) !== JSON.stringify(other[k]) : !NOISE.has(k));
  return keys.length ? Object.fromEntries(keys.map(k => [k, value[k]])) : value;
}

/** Compact JSON cell (Langfuse-style before/after column): monospace, clipped to a few lines. */
export function JsonCell({ value, other }: { value: unknown; other?: unknown }) {
  if (value == null) return <span className="text-muted-foreground">–</span>;
  return (
    <pre className="bg-surface-code max-h-16 max-w-72 overflow-hidden rounded-sm px-1.5 py-1 font-mono text-2xs leading-4 whitespace-pre-wrap break-all">
      {JSON.stringify(salient(value, other), null, 1)}
    </pre>
  );
}

const actorIcon = { user: User, api_key: KeyRound, system: Bot, anonymous: UserX } as const;

export function Actor({ e }: { e: Pick<AuditEntry, "actor_type" | "actor_label"> }) {
  const Icon = actorIcon[e.actor_type] ?? Bot;
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5" title={e.actor_type}>
      <Icon className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{e.actor_label ?? e.actor_type}</span>
    </span>
  );
}

const actionStyle: Record<string, string> = {
  create: "bg-light-green text-dark-green",
  login: "bg-light-green text-dark-green",
  update: "bg-light-yellow text-dark-yellow",
  password_change: "bg-light-yellow text-dark-yellow",
  revoke: "bg-light-red text-dark-red",
  login_failed: "bg-light-red text-dark-red",
  restore: "bg-light-red text-dark-red",
};

export function ActionBadge({ action }: { action: string }) {
  return <span className={cn("inline-flex rounded-md px-2 py-0.5 font-mono text-xs", actionStyle[action] ?? "bg-muted")}>{action}</span>;
}

type Flat = Record<string, string>;

function flatten(value: unknown, prefix = "", out: Flat = {}): Flat {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length && prefix) out[prefix] = "{}";
    for (const [k, v] of entries) flatten(v, prefix ? `${prefix}.${k}` : k, out);
  } else if (prefix) {
    out[prefix] = JSON.stringify(value);
  }
  return out;
}

/** Field-level diff of the before/after snapshots. */
export function SnapshotDiff({ before, after }: { before: unknown; after: unknown }) {
  const b = flatten(before), a = flatten(after);
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])].sort();
  if (!keys.length) return <p className="text-muted-foreground text-xs">No snapshot recorded for this action.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-xs">
        <thead><tr className="text-muted-foreground border-b text-left">
          <th className="py-1.5 pr-3 font-medium">Field</th><th className="py-1.5 pr-3 font-medium">Before</th><th className="py-1.5 font-medium">After</th>
        </tr></thead>
        <tbody>{keys.map(k => {
          const changed = b[k] !== a[k];
          return (
            <tr key={k} className={cn("border-b align-top last:border-0", changed && "bg-light-yellow/50")}>
              <td className="py-1.5 pr-3 font-mono">{k}</td>
              <td className={cn("py-1.5 pr-3 font-mono break-all", changed && b[k] !== undefined && "text-dark-red line-through")}>{b[k] ?? "–"}</td>
              <td className={cn("py-1.5 font-mono break-all", changed && a[k] !== undefined && "text-dark-green")}>{a[k] ?? "–"}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

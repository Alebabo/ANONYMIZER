/**
 * Simple policy editing: one action per data type. A rule that only names entity types (no category,
 * destination, risk or other condition) is "simple" and shows up in the editor; every other rule is kept
 * exactly as it is. Saving moves changed types into one rule per action and creates the next version.
 */

export type RuleJson = {
  id: string | null; description?: string | null; entity: string[] | null; category: string[] | null;
  risk: string[] | null; min_risk: string | null; role: string[] | null; signals: string[] | null;
  document_signals: string[] | null; max_confidence: number | null; destinations: string[] | null;
  action: string; priority: number; allow_critical: boolean;
};
export type PolicyJson = {
  name: string; version: number; description?: string | null; extends?: string | null; rules: RuleJson[];
  default_action: string; critical_floor?: boolean; critical_floor_action?: string; [k: string]: unknown;
};

/** Actions offered in the editor, in plain words. `local_only` and `block` stop the whole message. */
export const ACTIONS: { value: string; label: string; example: string }[] = [
  { value: "pseudonymize", label: "Placeholder", example: "Max → PERSON_001 (same value, same placeholder)" },
  { value: "redact", label: "Remove", example: "DE89… → [REDACTED]" },
  { value: "generalize", label: "Coarsen", example: "12.03.1985 → 1985" },
  { value: "mask", label: "Mask", example: "0151 2345678 → 0151 ****" },
  { value: "allow", label: "Keep", example: "sent unchanged" },
  { value: "local_only", label: "Don't send", example: "whole message stays with local models" },
  { value: "block", label: "Block", example: "whole message is never sent" },
];
export const actionLabel = (a: string) => ACTIONS.find(x => x.value === a)?.label ?? a;

/** Data types shown even when no rule names them yet (they then follow the default). */
export const ENTITY_GROUPS: { title: string; types: [string, string][] }[] = [
  { title: "People and places", types: [["person", "Names"], ["organization", "Companies"], ["location", "Places"]] },
  { title: "Contact", types: [["email", "E-mail"], ["phone", "Phone"], ["address", "Address"]] },
  { title: "Payment and IDs", types: [["iban", "IBAN"], ["credit_card", "Credit card"], ["bic", "BIC"],
    ["tax_id", "Tax ID"], ["tax_number", "Tax number"], ["social_security_number", "Social security no."], ["vat_id", "VAT ID"],
    ["id_document", "ID card / passport"], ["health_insurance_number", "Health insurance no."]] },
  { title: "Dates and amounts", types: [["date_of_birth", "Date of birth"], ["date", "Dates"], ["money", "Amounts"]] },
  { title: "Business references", types: [["customer_number", "Customer no."], ["order_number", "Order no."],
    ["ticket_number", "Ticket no."], ["contract_number", "Contract no."], ["invoice_number", "Invoice no."]] },
  { title: "Technical and vehicles", types: [["ip_address", "IP address"], ["license_plate", "Licence plate"]] },
];

// Same order as Action in the API: on a conflict the more restrictive action wins.
const SEVERITY = ["allow", "replace", "generalize", "mask", "pseudonymize", "tokenize", "redact", "review", "local_only", "block"];

const CONDITIONS = ["category", "risk", "min_risk", "role", "signals", "document_signals", "max_confidence", "destinations"] as const;

export const isSimple = (r: RuleJson) =>
  !!r.entity?.length && CONDITIONS.every(k => r[k] == null) && !r.priority && !r.allow_critical;

/** Action per entity type from the simple rules; types without one follow `default_action`. */
export function entityActions(p: PolicyJson): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of p.rules.filter(isSimple))
    for (const e of r.entity!)
      if (!(e in out) || SEVERITY.indexOf(r.action) > SEVERITY.indexOf(out[e]!)) out[e] = r.action;
  return out;
}

/** Every entity type the editor shows: the known groups plus types only this policy names. */
export function editorTypes(p: PolicyJson): { title: string; types: [string, string][] }[] {
  const known = new Set(ENTITY_GROUPS.flatMap(g => g.types.map(([t]) => t)));
  const extra = Object.keys(entityActions(p)).filter(t => !known.has(t)).map(t => [t, t] as [string, string]);
  return extra.length ? [...ENTITY_GROUPS, { title: "Other", types: extra }] : ENTITY_GROUPS;
}

/**
 * Next version with the given actions per type ("" = follow the default). Existing rules keep their ids
 * and order; a changed type leaves its rule and joins `editor_<action>`.
 */
export function applyChanges(p: PolicyJson, wanted: Record<string, string>, defaultAction: string): PolicyJson {
  const current = entityActions(p);
  const changed = Object.entries(wanted).filter(([t, a]) => (current[t] ?? "") !== a);
  const moved = new Set(changed.map(([t]) => t));
  const rules = p.rules.map(r => (isSimple(r) ? { ...r, entity: r.entity!.filter(e => !moved.has(e)) } : r));
  for (const [t, a] of changed) {
    if (!a) continue;
    // Changed types collect in one rule per action, so hand-written rules keep their meaning (and their id).
    const target = rules.find(r => r.id === `editor_${a}`);
    if (target) target.entity = [...(target.entity ?? []), t];
    else rules.push({ id: `editor_${a}`, description: "Set in the dashboard", entity: [t], category: null, risk: null, min_risk: null, role: null,
      signals: null, document_signals: null, max_confidence: null, destinations: null, action: a, priority: 0, allow_critical: false });
  }
  return {
    ...p, version: p.version + 1, default_action: defaultAction,
    rules: rules.filter(r => !(r.entity && !r.entity.length && CONDITIONS.every(k => r[k] == null))),
  };
}

const CATEGORY_LABELS: Record<string, string> = {
  special_category: "special categories (health, religion, union membership …)",
  criminal_data: "criminal records", personal_data: "personal data",
};

/** One sentence for a rule the simple editor does not touch. */
export function describeRule(r: RuleJson): string {
  const what = [
    r.entity?.length ? r.entity.join(", ") : null,
    r.category?.length ? r.category.map(c => CATEGORY_LABELS[c] ?? c).join(", ") : null,
    r.min_risk ? `risk ${r.min_risk} or higher` : null,
    r.risk?.length ? `risk ${r.risk.join("/")}` : null,
    r.signals?.length ? `near ${r.signals.join(", ")}` : null,
    r.document_signals?.length ? `in documents mentioning ${r.document_signals.join(", ")}` : null,
  ].filter(Boolean).join(" · ") || "everything";
  const where = r.destinations?.length ? ` going to ${r.destinations.join(" or ")} models` : "";
  return `${what[0]!.toUpperCase()}${what.slice(1)}${where} → ${actionLabel(r.action)}`;
}

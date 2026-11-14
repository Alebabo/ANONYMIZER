export type PrivacyLevel = "CRITICAL" | "GREY" | "UNCRITICAL";
export type Finding = { id: string; type: string; value: string; level: PrivacyLevel; start: number; end: number; reason: string };
type Rule = { type: string; level: PrivacyLevel; reason: string; pattern: RegExp };

const RULES: Rule[] = [
  { type: "IBAN", level: "CRITICAL", reason: "Bank account identifier", pattern: /\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b/g },
  { type: "German tax ID", level: "CRITICAL", reason: "Government-issued personal identifier", pattern: /\b\d{11}\b/g },
  { type: "Email address", level: "GREY", reason: "Directly identifying contact information", pattern: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi },
  { type: "Phone number", level: "GREY", reason: "Potentially identifying contact information", pattern: /(?<!\w)(?:\+49|0049|0)[\s./()-]*(?:\d[\s./()-]*){7,14}\b/g },
  { type: "German postcode", level: "GREY", reason: "Location information; assess together with surrounding context", pattern: /\b\d{5}\b/g },
  { type: "Legal citation", level: "UNCRITICAL", reason: "Public legal reference", pattern: /\b(?:§{1,2}\s*\d+[a-z]?\s*(?:Abs\.\s*\d+\s*)?(?:BGB|StGB|ZPO|StPO|GG|HGB|AO|GmbHG|AktG|VwGO|VwVfG)|Art\.\s*\d+\s*(?:GG|AEUV|EMRK))\b/gi }
];

function stableId(type: string, start: number, end: number) {
  return type.toLowerCase().replace(/[^a-z0-9]+/g, "-") + "-" + start + "-" + end;
}

export function analyzeText(text: string) {
  const findings: Finding[] = [];
  for (const rule of RULES) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      const value = match[0], start = match.index ?? 0, end = start + value.length;
      if (!findings.some(f => start < f.end && end > f.start)) {
        findings.push({ id: stableId(rule.type, start, end), type: rule.type, value, level: rule.level, start, end, reason: rule.reason });
      }
    }
  }
  findings.sort((a, b) => a.start - b.start);
  return {
    findings,
    counts: {
      CRITICAL: findings.filter(f => f.level === "CRITICAL").length,
      GREY: findings.filter(f => f.level === "GREY").length,
      UNCRITICAL: findings.filter(f => f.level === "UNCRITICAL").length
    },
    reviewRequired: true,
    safeToShare: false,
    limitations: [
      "Rule-based detection only; names, organisations, addresses and contextual identifiers may be missed.",
      "Unmatched text is not certified as uncritical.",
      "Human review is required before sharing content with an external AI provider."
    ]
  };
}

export function redactText(text: string, findings: Finding[], consentedGreyIds: string[] = []) {
  const replacements = findings.filter(f => f.level === "CRITICAL" || (f.level === "GREY" && !consentedGreyIds.includes(f.id))).sort((a, b) => b.start - a.start);
  let output = text;
  for (const f of replacements) output = output.slice(0, f.start) + "[REDACTED:" + f.type.toUpperCase().replace(/[^A-Z0-9]+/g, "_") + "]" + output.slice(f.end);
  return output;
}

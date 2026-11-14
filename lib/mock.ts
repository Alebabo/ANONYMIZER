// Illustrative example data only. No real content.
export type Risk = "Critical" | "Sensitive" | "Low";
export const detections = [
  { entity: "Person", category: "Personal Data", risk: "Critical" as Risk, confidence: 98.2, action: "Pseudonymized", policy: "Legal-PII-v1", time: "14:32:08" },
  { entity: "IBAN", category: "Financial Data", risk: "Critical" as Risk, confidence: 99.9, action: "Redacted", policy: "Legal-PII-v1", time: "14:32:08" },
  { entity: "Aktenzeichen", category: "Legal Data", risk: "Sensitive" as Risk, confidence: 91.4, action: "Pseudonymized", policy: "Legal-PII-v1", time: "14:30:41" },
  { entity: "Health data", category: "Special Categories", risk: "Critical" as Risk, confidence: 87.0, action: "Blocked", policy: "Legal-PII-v1", time: "14:28:19" },
  { entity: "Organization", category: "Business Secrets", risk: "Low" as Risk, confidence: 72.5, action: "Allowed", policy: "Legal-PII-v1", time: "14:27:02" },
];
export const traces = [
  { id: "req_8f29a1", route: "POST /v1/chat/completions", status: "Processed", provider: "openai", model: "gpt-4o", entities: 4, latency: "182 ms", time: "14:32" },
  { id: "req_41c07e", route: "POST /v1/chat/completions", status: "Blocked", provider: "anthropic", model: "claude", entities: 2, latency: "64 ms", time: "14:30" },
  { id: "req_b92d10", route: "POST /v1/anonymize", status: "Processed", provider: "-", model: "-", entities: 7, latency: "95 ms", time: "14:28" },
];
export const traceSteps = [
  ["Request received", "Input received from application"],
  ["Privacy detection", "4 entities detected"],
  ["Classification", "2 critical · 2 sensitive"],
  ["Policy evaluation", "Legal-PII-v1 applied"],
  ["Anonymization", "4 transformations applied"],
  ["Provider request", "Request sent to configured LLM"],
];
export const policyYaml = `name: legal-default
version: 1
rules:
  - entity: person
    action: pseudonymize
  - entity: iban
    action: redact
  - entity: health_data
    action: block
  - entity: client_secret
    action: block
default_action: allow`;

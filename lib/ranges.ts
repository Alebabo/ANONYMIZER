export const RANGES = [
  { key: "1h", label: "Past 1 hour", hours: 1 },
  { key: "24h", label: "Past 24 hours", hours: 24 },
  { key: "7d", label: "Past 7 days", hours: 24 * 7 },
  { key: "30d", label: "Past 30 days", hours: 24 * 30 },
] as const;

export const rangeFor = (key: string | undefined) => RANGES.find(r => r.key === key) ?? RANGES[1];

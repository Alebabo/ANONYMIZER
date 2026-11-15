/**
 * Cato brand mark: a Roman colonnade (Forum Romanum) whose entablature is a
 * data stack; the middle layer carries the redaction block. Infrastructure
 * (layers + columns), protection (redaction) and Rome (Cato) in one sign.
 * Lines use currentColor; the redaction block is the single accent color.
 */

export const ACCENT = "#3D5AFE";

export function Logomark({ className, title = "Cato" }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label={title || undefined} aria-hidden={title ? undefined : true}>
      <g fill="currentColor">
        <rect x="2.5" y="3" width="27" height="4.5" rx="1.25" />
        <rect x="2.5" y="9.5" width="6.5" height="4.5" rx="1.25" />
        <rect x="23" y="9.5" width="6.5" height="4.5" rx="1.25" />
        <rect x="3.5" y="16" width="6.5" height="2" /><path d="M5.1 18H8.4L8.9 27H4.6Z" /><rect x="3.5" y="27" width="6.5" height="2" />
        <rect x="12.75" y="16" width="6.5" height="2" /><path d="M14.35 18H17.65L18.15 27H13.85Z" /><rect x="12.75" y="27" width="6.5" height="2" />
        <rect x="22" y="16" width="6.5" height="2" /><path d="M23.6 18H26.9L27.4 27H23.1Z" /><rect x="22" y="27" width="6.5" height="2" />
      </g>
      <rect x="11" y="9" width="10" height="5.5" fill={ACCENT} />
    </svg>
  );
}

/** Mark + "cato" set in the UI sans. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className ?? ""}`} aria-label="Cato">
      <Logomark className="h-6 w-6" title="" />
      <span aria-hidden className="text-[17px] leading-none font-bold tracking-[-0.03em]">cato</span>
    </span>
  );
}

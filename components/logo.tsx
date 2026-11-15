/**
 * Cato brand marks: lines of text with one redacted segment.
 * Lines use currentColor (follow the theme); the redaction block is the
 * single accent color. 4 lines on a 32-unit grid stay legible at 16 px.
 */

export const ACCENT = "#3D5AFE";

export function Logomark({ className, title = "Cato" }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label={title}>
      <g fill="currentColor">
        <rect x="4" y="5" width="24" height="3.5" rx="1.75" />
        <rect x="4" y="11" width="18" height="3.5" rx="1.75" />
        <rect x="4" y="17" width="5" height="3.5" rx="1.75" />
        <rect x="23" y="17" width="5" height="3.5" rx="1.75" />
        <rect x="4" y="23" width="15" height="3.5" rx="1.75" />
      </g>
      <rect x="11" y="16" width="10" height="5.5" fill={ACCENT} />
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

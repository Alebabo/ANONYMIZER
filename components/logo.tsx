/**
 * Cato brand marks. Geometric construction (no font dependency):
 * the solid block is a redaction bar – "something here is protected".
 * Colors come from currentColor so the marks follow the theme.
 */

export function Wordmark({ className, title = "Cato" }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 126 40" className={className} role="img" aria-label={title} fill="none">
      <g stroke="currentColor" strokeWidth={6.5}>
        <path d="M21.5 15.5A11 11 0 1 0 21.5 32.5" />
        <circle cx="38" cy="24" r="10.75" />
        <path d="M48.75 12.5V36" />
        <path d="M62 5V36M56.5 14H69.5" />
        <circle cx="86" cy="24" r="10.75" />
      </g>
      <rect x="104" y="12" width="20" height="24" fill="currentColor" />
    </svg>
  );
}

/** Square app mark: "c" plus redaction bar. ``inverted`` draws a filled tile. */
export function Logomark({ className, inverted = true }: { className?: string; inverted?: boolean }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role="img" aria-label="Cato">
      {inverted && <rect width="64" height="64" rx="14" fill="currentColor" />}
      <path
        d="M30 22.5A12.5 12.5 0 1 0 30 41.5"
        fill="none"
        stroke={inverted ? "var(--logo-contrast, #fff)" : "currentColor"}
        strokeWidth={7}
      />
      <rect x="35" y="19.5" width="14" height="25" fill={inverted ? "var(--logo-contrast, #fff)" : "currentColor"} />
    </svg>
  );
}

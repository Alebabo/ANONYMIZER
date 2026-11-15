/**
 * Cato brand mark: a single Roman column (capital, shaft, base) whose
 * centre channel is the accent color: the protected core inside the pillar
 * that carries AI workloads. Lines use currentColor; one accent color.
 */

export const ACCENT = "#3D5AFE";

export function Logomark({ className, title = "Cato" }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label={title || undefined} aria-hidden={title ? undefined : true}>
      <g fill="currentColor">
        <rect x="7" y="3" width="18" height="5" />
        <rect x="10" y="8" width="4.5" height="16" />
        <rect x="17.5" y="8" width="4.5" height="16" />
        <rect x="7" y="24" width="18" height="5" />
      </g>
      <rect x="14.5" y="8" width="3" height="16" fill={ACCENT} />
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

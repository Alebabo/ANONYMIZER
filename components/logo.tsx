import { useId } from "react";

/**
 * OpenAnonymizer brand mark: a solid square (the original data) behind a second square whose
 * content is struck through by diagonal stripes (the protected copy that leaves). One color,
 * currentColor, so it follows light and dark mode. Same geometry as app/icon.svg and public/brand.
 */

// Diagonal bands along x + y, clipped to the front square.
const BANDS: [number, number][] = [[97, 116.5], [132.5, 150.5], [167, 200]];
const band = ([a, b]: [number, number]) => `${a + 100},-100 ${b + 100},-100 ${b - 200},200 ${a - 200},200`;

export function Logomark({ className, title = "OpenAnonymizer" }: { className?: string; title?: string }) {
  const id = useId();
  return (
    <svg viewBox="0 -2 100 100" className={className} role="img" aria-label={title || undefined} aria-hidden={title ? undefined : true}>
      <defs>
        <mask id={`${id}b`}>
          <rect x="0" y="0" width="74.5" height="73" rx="14.5" fill="#fff" />
          <rect x="27" y="25" width="74" height="72" rx="15.5" fill="#000" />
        </mask>
        <clipPath id={`${id}f`}><rect x="28" y="26" width="72" height="70" rx="14.5" /></clipPath>
      </defs>
      <g fill="currentColor">
        <rect x="0" y="0" width="74.5" height="73" rx="14.5" mask={`url(#${id}b)`} />
        <g clipPath={`url(#${id}f)`}>{BANDS.map(b => <polygon key={b[0]} points={band(b)} />)}</g>
      </g>
    </svg>
  );
}

/** Mark + "openanonymizer" set in the UI sans. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className ?? ""}`} aria-label="OpenAnonymizer">
      <Logomark className="h-6 w-6" title="" />
      <span aria-hidden className="text-[17px] leading-none font-bold tracking-[-0.03em]"><span className="font-normal">open</span>anonymizer</span>
    </span>
  );
}

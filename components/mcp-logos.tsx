/** Simplified marks of the MCP systems a proxy can log. Unknown systems get a monogram. */
const BLUE = "#0052CC", LIGHT = "#2684FF";

function Jira() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className="size-full">
      <path fill={LIGHT} d="M16 2 4 14l4 4 8-8 8 8 4-4z" opacity=".55" />
      <path fill={BLUE} d="m16 10-8 8 8 8 8-8z" />
    </svg>
  );
}
function Confluence() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className="size-full">
      <path fill={BLUE} d="M3 22c3-5 6-7 9.500-7 3.500 0 6.500 2.500 9.500 2.500 2 0 3.500-.800 5-2.500l2 5c-2 2.500-4.500 4-7.500 4-3.500 0-6.500-2.500-9.500-2.500-2 0-3.500.800-5 2.500z" />
      <path fill={LIGHT} d="M29 10c-3 5-6 7-9.500 7-3.500 0-6.500-2.500-9.500-2.500-2 0-3.500.800-5 2.500l-2-5c2-2.500 4.500-4 7.500-4 3.500 0 6.500 2.500 9.500 2.500 2 0 3.500-.800 5-2.500z" />
    </svg>
  );
}
function Bitbucket() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className="size-full">
      <path fill={BLUE} d="M4 5h24l-3.500 21H7.500z" />
      <path fill="#fff" d="M11 12h10l-1 7h-8z" opacity=".9" />
      <path fill={LIGHT} d="M5 14h22l-.800 5H5.800z" opacity=".0" />
    </svg>
  );
}

const MARKS: Record<string, () => React.JSX.Element> = { jira: Jira, confluence: Confluence, bitbucket: Bitbucket };
export const MCP_LABELS: Record<string, string> = { jira: "Jira", confluence: "Confluence", bitbucket: "Bitbucket" };

export function McpLogo({ name, className = "size-8" }: { name: string; className?: string }) {
  const Mark = MARKS[name];
  return (
    <span className={`inline-flex shrink-0 items-center justify-center ${className}`}>
      {Mark ? <Mark /> : (
        <span aria-hidden className="bg-muted text-muted-foreground flex size-full items-center justify-center rounded-md text-sm font-bold uppercase">
          {name.slice(0, 1)}
        </span>
      )}
    </span>
  );
}

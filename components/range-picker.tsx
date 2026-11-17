"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Calendar, Check, ChevronDown } from "lucide-react";
import { RANGES, rangeFor } from "@/lib/ranges";
import { cn } from "@/lib/utils";


/** Date range dropdown in the style of the Langfuse dashboard toolbar. Writes ?range= to the URL. */
export function RangePicker({ value }: { value: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const path = usePathname();
  const params = useSearchParams();
  const current = rangeFor(value);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const href = (key: string) => {
    const p = new URLSearchParams(params.toString());
    p.set("range", key);
    return `${path}?${p}`;
  };
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(o => !o)} aria-haspopup="listbox" aria-expanded={open}
              className="border-border-contrast bg-background hover:bg-accent inline-flex h-8 items-center gap-2 rounded-md border px-3 text-sm">
        <Calendar className="text-muted-foreground h-4 w-4" />{current.label}
        <ChevronDown className="text-muted-foreground h-3.5 w-3.5" />
      </button>
      {open && (
        <ul role="listbox" className="bg-popover text-popover-foreground absolute right-0 z-30 mt-1 w-44 rounded-md border p-1 shadow-md">
          {RANGES.map(r => (
            <li key={r.key} role="option" aria-selected={r.key === current.key}>
              <Link href={href(r.key)} onClick={() => setOpen(false)}
                    className={cn("hover:bg-accent flex h-8 items-center justify-between rounded-sm px-2 text-sm",
                      r.key === current.key && "font-medium")}>
                {r.label}{r.key === current.key && <Check className="h-3.5 w-3.5" />}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

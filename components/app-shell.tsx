"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, BarChart3, Gauge, KeyRound, Menu, Network, X, Plug, ScrollText, Settings, ShieldCheck, Waypoints } from "lucide-react";
import { cn } from "@/lib/utils";

const workspace = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/gateway", label: "Gateway", icon: Waypoints },
  { href: "/privacy", label: "Privacy", icon: ShieldCheck },
  { href: "/traces", label: "Traces", icon: Activity },
  { href: "/metrics", label: "Metrics", icon: BarChart3 },
];
const configuration = [
  { href: "/policies", label: "Policies", icon: ScrollText },
  { href: "/api-keys", label: "API Keys", icon: KeyRound },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/settings", label: "Settings", icon: Settings },
];

function Group({ title, items, onNavigate }: { title: string; items: typeof workspace; onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <div className="px-2 py-2">
      <div className="text-muted-foreground px-2 pb-1 text-2xs uppercase tracking-wide">{title}</div>
      {items.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} onClick={onNavigate} className={cn("flex h-9 md:h-7 items-center gap-2 rounded-md px-2 text-sm", active ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium" : "text-sidebar-foreground hover:bg-sidebar-accent/60")}>
            <Icon className="h-4 w-4" />{label}
          </Link>
        );
      })}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <div className="flex h-dvh flex-col md:flex-row">
      {/* Mobile top bar */}
      <div className="bg-sidebar border-sidebar-border relative z-50 flex h-12 shrink-0 items-center gap-2 border-b px-3 md:hidden">
        <button
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          aria-controls="cato-nav"
          onClick={() => setOpen(o => !o)}
          className="hover:bg-sidebar-accent flex h-9 w-9 items-center justify-center rounded-md"
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
        <Logo />
      </div>

      {open && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setOpen(false)} aria-hidden />}

      <aside
        id="cato-nav"
        className={cn(
          "bg-sidebar border-sidebar-border z-40 flex w-64 shrink-0 flex-col overflow-y-auto border-r md:static md:w-56 md:translate-x-0",
          "fixed inset-y-0 left-0 transition-transform duration-150 md:transition-none",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="hidden h-12 items-center gap-2 px-4 md:flex"><Logo /></div>
        <div className="h-12 md:hidden" />
        <Group title="Workspace" items={workspace} onNavigate={() => setOpen(false)} />
        <Group title="Configuration" items={configuration} onNavigate={() => setOpen(false)} />
      </aside>
      <main className="min-w-0 flex-1 overflow-auto">{children}</main>
    </div>
  );
}

function Logo() {
  return (
    <>
      <span className="bg-primary text-primary-foreground flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold">C</span>
      <span className="text-sm font-medium">Cato</span>
      <Network className="text-muted-foreground ml-auto hidden h-3.5 w-3.5 md:block" />
    </>
  );
}

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <header className="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b px-4 py-2 md:px-6">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3">
        <h1 className="truncate text-lg font-bold">{title}</h1>
        {description && <span className="text-muted-foreground text-xs">{description}</span>}
      </div>
      {children && <div className="flex gap-2">{children}</div>}
    </header>
  );
}

/** Horizontal scroll container for dense tables on small screens. */
export function TableScroll({ children, minWidth = 640 }: { children: React.ReactNode; minWidth?: number }) {
  return (
    <div className="w-full overflow-x-auto">
      <div style={{ minWidth }}>{children}</div>
    </div>
  );
}

const riskStyle: Record<string, string> = {
  Critical: "bg-light-red text-dark-red",
  Sensitive: "bg-light-yellow text-dark-yellow",
  Low: "bg-light-green text-dark-green",
  Blocked: "bg-light-red text-dark-red",
  Processed: "bg-light-green text-dark-green",
};
export function Badge({ children }: { children: string }) {
  return <span className={cn("inline-flex rounded-md px-2 py-0.5 text-xs", riskStyle[children] ?? "bg-muted text-muted-foreground")}>{children}</span>;
}

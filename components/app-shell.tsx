"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import {
  Activity, BarChart3, ChevronRight, FileClock, FileText, FlaskConical, Home, Info, KeyRound, LogOut, Menu, MessagesSquare, Network,
  PanelLeft, Plug, ScrollText, Settings, ShieldCheck, Waypoints, X,
} from "lucide-react";
import { logout } from "@/app/actions";
import { cn } from "@/lib/utils";
import { Logomark, Wordmark } from "@/components/logo";

// Navigation follows the Langfuse layout: unlabeled home, product groups, configuration pinned to the bottom.
const groups: { title?: string; items: NavItem[] }[] = [
  { items: [{ href: "/", label: "Home", icon: Home }] },
  {
    title: "Observability",
    items: [
      { href: "/traces", label: "Traces", icon: Activity },
      { href: "/conversations", label: "Conversations", icon: MessagesSquare },
      { href: "/proxy", label: "MCP Proxy", icon: Network },
      { href: "/gateway", label: "Gateway", icon: Waypoints },
    ],
  },
  {
    title: "Privacy",
    items: [
      { href: "/privacy", label: "Detections", icon: ShieldCheck },
      { href: "/metrics", label: "Metrics", icon: BarChart3 },
      { href: "/policies", label: "Policies", icon: ScrollText },
    ],
  },
  {
    title: "Prompt Management",
    items: [
      { href: "/prompts", label: "Prompts", icon: FileText },
      { href: "/playground", label: "Playground", icon: FlaskConical },
    ],
  },
];
const bottom: NavItem[] = [
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/api-keys", label: "API Keys", icon: KeyRound },
  { href: "/settings/audit-logs", label: "Audit Logs", icon: FileClock },
  { href: "/settings", label: "Settings", icon: Settings, exclude: "/settings/audit-logs" },
];

type NavItem = { href: string; label: string; icon: typeof Home; exclude?: string };

export type Account = { name: string; email: string; role: string; organization: string; demo: boolean };

const AccountContext = createContext<Account | null>(null);
const COLLAPSE_KEY = "anonymizer.sidebar.collapsed";

function isActive(path: string, { href, exclude }: NavItem) {
  if (href === "/") return path === "/";
  return (path === href || path.startsWith(href + "/")) && !(exclude && path.startsWith(exclude));
}

function NavLink({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const path = usePathname();
  const active = isActive(path, item);
  const Icon = item.icon;
  return (
    <Link href={item.href} onClick={onNavigate} title={collapsed ? item.label : undefined}
          aria-current={active ? "page" : undefined}
          className={cn("flex h-9 items-center gap-2 rounded-md px-2 text-sm md:h-8",
            collapsed && "md:justify-center md:px-0",
            active ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
              : "text-sidebar-foreground hover:bg-sidebar-accent/60")}>
      <Icon className="h-4 w-4 shrink-0" />
      <span className={cn("truncate", collapsed && "md:sr-only")}>{item.label}</span>
    </Link>
  );
}

function initials(name: string) {
  return name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(p => p[0]!.toUpperCase()).join("") || "?";
}

function UserRow({ account, collapsed }: { account: Account; collapsed: boolean }) {
  return (
    <div className={cn("flex items-center gap-2 rounded-md p-2", collapsed && "md:justify-center md:p-1")}>
      <span className="bg-sidebar-accent text-sidebar-accent-foreground flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-medium"
            title={collapsed ? account.name : undefined}>
        {initials(account.name)}
      </span>
      <div className={cn("min-w-0 flex-1", collapsed && "md:hidden")}>
        <div className="truncate text-sm font-medium">{account.name}</div>
        <div className="text-muted-foreground truncate text-xs">
          {account.demo ? "Demo mode" : `${account.email} · ${account.role}`}
        </div>
      </div>
      {!account.demo && (
        <form action={logout} className={cn(collapsed && "md:hidden")}>
          <button type="submit" aria-label="Sign out" title="Sign out"
                  className="hover:bg-sidebar-accent text-muted-foreground flex h-7 w-7 items-center justify-center rounded-md">
            <LogOut className="h-4 w-4" />
          </button>
        </form>
      )}
    </div>
  );
}

export function AppShell({ children, account }: { children: React.ReactNode; account: Account }) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const path = usePathname();
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    try { setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1"); } catch { /* storage unavailable */ }
  }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  const toggle = () => setCollapsed(c => {
    try { localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1"); } catch { /* storage unavailable */ }
    return !c;
  });
  const close = () => setOpen(false);
  return (
    <AccountContext.Provider value={account}>
      <div className="flex h-dvh flex-col md:flex-row">
        {/* Mobile top bar */}
        <div className="bg-sidebar border-sidebar-border relative z-50 flex h-12 shrink-0 items-center gap-2 border-b px-3 md:hidden">
          <button type="button" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open}
                  aria-controls="anonymizer-nav" onClick={() => setOpen(o => !o)}
                  className="hover:bg-sidebar-accent flex h-9 w-9 items-center justify-center rounded-md">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <Link href="/" aria-label="Anonymizer – Home" className="text-foreground flex items-center"><Wordmark /></Link>
        </div>

        {open && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={close} aria-hidden />}

        <aside id="anonymizer-nav"
               className={cn(
                 "bg-sidebar border-sidebar-border z-40 flex w-64 shrink-0 flex-col overflow-y-auto border-r md:static md:translate-x-0",
                 "fixed inset-y-0 left-0 transition-transform duration-150 md:transition-[width]",
                 collapsed ? "md:w-12" : "md:w-56",
                 open ? "translate-x-0" : "-translate-x-full",
               )}>
          <div className={cn("hidden h-12 shrink-0 items-center px-3 md:flex", collapsed && "md:justify-center md:px-0")}>
            <Link href="/" aria-label="Anonymizer – Home" className="text-foreground flex items-center">
              {collapsed ? <Logomark className="h-6 w-6" title="" /> : <Wordmark />}
            </Link>
          </div>
          <div className="h-12 md:hidden" />
          <nav className="flex flex-1 flex-col gap-3 px-2 py-1" aria-label="Main">
            {groups.map((g, i) => (
              <div key={i}>
                {g.title && (
                  <div className={cn("text-muted-foreground px-2 pb-1 text-2xs", collapsed && "md:sr-only")}>{g.title}</div>
                )}
                <div className="space-y-0.5">
                  {g.items.map(item => <NavLink key={item.href} item={item} collapsed={collapsed} onNavigate={close} />)}
                </div>
              </div>
            ))}
            <div className="mt-auto space-y-0.5 pt-3">
              {bottom.map(item => <NavLink key={item.href} item={item} collapsed={collapsed} onNavigate={close} />)}
            </div>
          </nav>
          <div className="border-sidebar-border border-t p-1.5">
            <UserRow account={account} collapsed={collapsed} />
            <button type="button" onClick={toggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                    title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                    className="text-muted-foreground hover:bg-sidebar-accent hidden h-8 w-full items-center gap-2 rounded-md px-2 text-xs md:flex">
              <PanelLeft className={cn("h-4 w-4 shrink-0", collapsed && "mx-auto")} />
              <span className={cn(collapsed && "sr-only")}>Collapse</span>
            </button>
          </div>
        </aside>
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </AccountContext.Provider>
  );
}

/**
 * Langfuse-style page header: breadcrumb (organization / workspace / parent), title with an info
 * hint, actions on the right. `description` shows as tooltip; `meta` stays visible next to the title.
 */
export function PageHeader({ title, description, meta, parent, children }: {
  title: string; description?: string; meta?: React.ReactNode; parent?: { label: string; href: string };
  children?: React.ReactNode;
}) {
  const account = useContext(AccountContext);
  return (
    <header className="bg-background sticky top-0 z-20 border-b px-4 md:px-6">
      <nav aria-label="Breadcrumb" className="text-muted-foreground flex h-8 items-center gap-1 overflow-hidden text-xs">
        <span className="truncate">{account?.organization ?? "Organization"}</span>
        <ChevronRight className="h-3 w-3 shrink-0" />
        <Link href="/" className="hover:text-foreground truncate">Anonymizer</Link>
        {parent && <>
          <ChevronRight className="h-3 w-3 shrink-0" />
          <Link href={parent.href} className="hover:text-foreground truncate">{parent.label}</Link>
        </>}
      </nav>
      <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 pb-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <h1 className="truncate text-lg font-bold">{title}</h1>
          {description && (
            <span title={description} aria-label={description} className="text-muted-foreground inline-flex cursor-help">
              <Info className="h-3.5 w-3.5" />
            </span>
          )}
          {meta && <div className="text-muted-foreground ml-1 flex min-w-0 flex-wrap items-center gap-1.5 text-xs">{meta}</div>}
        </div>
        {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
      </div>
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

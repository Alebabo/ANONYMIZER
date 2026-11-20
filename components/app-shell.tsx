"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import {
  Activity, ChevronRight, Info, LogOut, Menu, MessageSquare, PanelLeft, Settings, Table2, X,
} from "lucide-react";
import { logout } from "@/app/actions";
import { cn } from "@/lib/utils";
import { Logomark, Wordmark } from "@/components/logo";

type Tab = { href: string; label: string };

// Pages that belong together share one nav entry and switch via tabs in the page header.
const sections = {
  settings: {
    label: "Settings",
    tabs: [
      { href: "/settings", label: "General" }, { href: "/settings/policies", label: "Policies" },
      { href: "/api-keys", label: "API Keys" }, { href: "/settings/members", label: "Members" },
      { href: "/settings/audit-logs", label: "Audit Logs" },
    ],
  },
} satisfies Record<string, { label: string; tabs: Tab[] }>;
type Section = keyof typeof sections;

const main: NavItem[] = [
  { href: "/", label: "Chat", icon: MessageSquare },
  { href: "/traces", label: "Traces", icon: Activity },
  { href: "/playground", label: "CSV", icon: Table2 },
];
const bottom: NavItem[] = [
  { href: "/settings", label: "Settings", icon: Settings, section: "settings" },
];

type NavItem = { href: string; label: string; icon: typeof Activity; section?: Section };

const under = (path: string, href: string) => path === href || path.startsWith(href + "/");

/** The tab with the longest matching href, so /settings/members does not also light up /settings. */
function activeTab(path: string, tabs: Tab[]) {
  return tabs.filter(t => under(path, t.href)).sort((a, b) => b.href.length - a.href.length)[0];
}

export type Account = { name: string; email: string; role: string; organization: string; demo: boolean };

const AccountContext = createContext<Account | null>(null);
const COLLAPSE_KEY = "anonymizer.sidebar.collapsed";

function isActive(path: string, { href, section }: NavItem) {
  if (href === "/") return path === "/";
  return section ? !!activeTab(path, sections[section].tabs) : under(path, href);
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
          <Link href="/" aria-label="OpenAnonymizer – Home" className="text-foreground flex items-center"><Wordmark /></Link>
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
            <Link href="/" aria-label="OpenAnonymizer – Home" className="text-foreground flex items-center">
              {collapsed ? <Logomark className="h-6 w-6" title="" /> : <Wordmark />}
            </Link>
          </div>
          <div className="h-12 md:hidden" />
          <nav className="flex flex-1 flex-col gap-3 px-2 py-1" aria-label="Main">
            <div className="space-y-0.5">
              {main.map(item => <NavLink key={item.href} item={item} collapsed={collapsed} onNavigate={close} />)}
            </div>
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
 * `section` adds the tab bar of that section below the title.
 */
export function PageHeader({ title, description, meta, parent, section, children }: {
  title: string; description?: string; meta?: React.ReactNode; parent?: { label: string; href: string };
  section?: Section; children?: React.ReactNode;
}) {
  const account = useContext(AccountContext);
  const path = usePathname();
  const tabs = section ? sections[section].tabs : [];
  const current = activeTab(path, tabs);
  if (section && !parent && title !== sections[section].label) parent = { label: sections[section].label, href: tabs[0]!.href };
  return (
    <header className="bg-background sticky top-0 z-20 border-b px-4 md:px-6">
      <nav aria-label="Breadcrumb" className="text-muted-foreground flex h-8 items-center gap-1 overflow-hidden text-xs">
        <span className="truncate">{account?.organization ?? "Organization"}</span>
        <ChevronRight className="h-3 w-3 shrink-0" />
        <Link href="/" className="hover:text-foreground truncate">OpenAnonymizer</Link>
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
      {tabs.length > 0 && (
        <nav aria-label={sections[section!].label} className="-mb-px flex gap-1 overflow-x-auto">
          {tabs.map(t => (
            <Link key={t.href} href={t.href} aria-current={t === current ? "page" : undefined}
                  className={cn("border-b-2 px-2 py-2 text-sm whitespace-nowrap",
                    t === current ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground border-transparent")}>
              {t.label}
            </Link>
          ))}
        </nav>
      )}
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

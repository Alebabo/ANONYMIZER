"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Gauge, KeyRound, Network, Plug, ScrollText, Settings, ShieldCheck, Waypoints } from "lucide-react";
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

function Group({ title, items }: { title: string; items: typeof workspace }) {
  const path = usePathname();
  return (
    <div className="px-2 py-2">
      <div className="text-muted-foreground px-2 pb-1 text-2xs uppercase tracking-wide">{title}</div>
      {items.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} className={cn("flex h-7 items-center gap-2 rounded-md px-2 text-sm", active ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium" : "text-sidebar-foreground hover:bg-sidebar-accent/60")}>
            <Icon className="h-4 w-4" />{label}
          </Link>
        );
      })}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <aside className="bg-sidebar border-sidebar-border flex w-56 shrink-0 flex-col border-r">
        <div className="flex h-12 items-center gap-2 px-4">
          <span className="bg-primary text-primary-foreground flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold">C</span>
          <span className="text-sm font-medium">Cato</span>
          <Network className="text-muted-foreground ml-auto h-3.5 w-3.5" />
        </div>
        <Group title="Workspace" items={workspace} />
        <Group title="Configuration" items={configuration} />
      </aside>
      <main className="min-w-0 flex-1 overflow-auto">{children}</main>
    </div>
  );
}

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <header className="flex h-12 items-center justify-between border-b px-6">
      <div className="flex items-baseline gap-3">
        <h1 className="text-lg font-bold">{title}</h1>
        {description && <span className="text-muted-foreground text-xs">{description}</span>}
      </div>
      <div className="flex gap-2">{children}</div>
    </header>
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

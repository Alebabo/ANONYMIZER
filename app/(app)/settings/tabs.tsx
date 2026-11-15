"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const tabs = [
  { href: "/settings", label: "General" },
  { href: "/settings/members", label: "Members" },
  { href: "/settings/audit-logs", label: "Audit Logs" },
];

export function SettingsTabs() {
  const path = usePathname();
  return (
    <nav aria-label="Settings" className="flex gap-1 overflow-x-auto border-b px-4 md:px-6">
      {tabs.map(t => {
        const active = t.href === "/settings" ? path === t.href : path.startsWith(t.href);
        return (
          <Link key={t.href} href={t.href} aria-current={active ? "page" : undefined}
                className={cn("-mb-px border-b-2 px-2 py-2 text-sm whitespace-nowrap",
                  active ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground border-transparent")}>
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

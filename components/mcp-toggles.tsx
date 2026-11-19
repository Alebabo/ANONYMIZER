"use client";
import { useState, useTransition } from "react";
import { setProxyUpstream } from "@/app/actions";
import { McpLogo, MCP_LABELS } from "@/components/mcp-logos";
import { Pill } from "@/components/dashboard";
import type { ProxyUpstream } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

/** One card per MCP system with a switch: on = its calls go through OpenAnonymizer and are logged. */
export function McpToggles({ upstreams }: { upstreams: ProxyUpstream[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {upstreams.map(u => <Toggle key={u.name} u={u} />)}
    </div>
  );
}

function Toggle({ u }: { u: ProxyUpstream }) {
  const [on, setOn] = useState(u.enabled);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const label = MCP_LABELS[u.name] ?? u.name;
  const flip = () => {
    const next = !on;
    setOn(next);
    setError(null);
    start(async () => {
      const fd = new FormData();
      fd.set("name", u.name);
      fd.set("enabled", String(next));
      const res = await setProxyUpstream({}, fd);
      if (res.error) { setOn(!next); setError(res.error); }
    });
  };
  return (
    <div className={cn("flex items-center gap-3 rounded-lg border p-3", on && "border-primary-accent/50 bg-surface-sunken")}>
      <McpLogo name={u.name} className="size-9" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-bold">{label}</div>
        <div className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
          {on ? <Pill value={u.connected ? "connected" : "disconnected"} /> : <span>not logged</span>}
          {on && u.connected && <span>{u.tools_exposed} tools · mode {u.mode}</span>}
          {on && !u.connected && u.error && <span>{u.error}</span>}
        </div>
        {error && <p role="alert" className="text-dark-red mt-1 text-xs">{error}</p>}
      </div>
      <button type="button" role="switch" aria-checked={on} aria-label={`Log ${label}`} disabled={pending} onClick={flip}
              className={cn("relative h-6 w-11 shrink-0 rounded-full border transition-colors disabled:opacity-60",
                            on ? "bg-primary-accent border-transparent" : "bg-control-track border-control-border")}>
        <span className={cn("absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform", on && "translate-x-5")} />
      </button>
    </div>
  );
}

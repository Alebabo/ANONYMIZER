import Link from "next/link";
import { SourceBanner } from "@/components/dashboard";
import { Chip } from "@/components/widgets";
import { getInfo, getMe, getPolicies, getPolicy, getSources } from "@/lib/anonymizer-api";
import { examplePolicyYaml } from "@/lib/mock";
import type { PolicyJson } from "@/lib/policy-edit";
import { cn } from "@/lib/utils";
import { PolicyEditor } from "./editor";

export const dynamic = "force-dynamic";

export default async function Policies({ searchParams }: { searchParams: Promise<{ name?: string }> }) {
  const [{ data: policies, source }, { data: info }, { data: sources }, { data: me }] =
    await Promise.all([getPolicies(), getInfo(), getSources(), getMe()]);
  // Which part of OpenAnonymizer uses which policy, so it is clear what a change affects.
  const usedBy: Record<string, string[]> = {};
  const use = (name: string | null | undefined, what: string) => { if (name) (usedBy[name] ??= []).push(what); };
  use(info.default_policy, "Gateway & API");
  use(sources.conversation_policy ?? "support-default", "Playground, conversations & MCP datasets");
  const { name } = await searchParams;
  const active = policies.find(p => p.name === name) ?? policies.find(p => p.name === "support-default") ?? policies[0];
  const detail = active ? (await getPolicy(active.name)).data as PolicyJson | null : null;

  return (
    <>
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <div className="flex flex-wrap gap-2">
          {policies.map(p => (
            <Link key={p.name} href={`/settings/policies?name=${encodeURIComponent(p.name)}`}
                  aria-current={p.name === active?.name ? "page" : undefined}
                  className={cn("rounded-lg border px-3 py-2 text-left text-sm",
                    p.name === active?.name ? "bg-muted border-border-contrast" : "hover:bg-muted/50")}>
              <div className="font-medium">{p.name} <span className="text-muted-foreground font-normal">v{p.version}</span></div>
              <div className="text-muted-foreground text-2xs">{usedBy[p.name]?.join(" · ") ?? "not in use"}</div>
            </Link>
          ))}
        </div>

        {detail ? (
          <>
            {detail.description && <p className="text-muted-foreground max-w-3xl text-xs">{detail.description}</p>}
            {detail.extends && <Chip>extends {detail.extends}</Chip>}
            <PolicyEditor key={`${detail.name}@${detail.version}`} policy={detail} canEdit={source.live && me.role === "admin"} />
          </>
        ) : (
          <pre className="bg-surface-code overflow-auto rounded-md p-4 font-mono text-xs">{examplePolicyYaml}</pre>
        )}
        <p className="text-muted-foreground text-xs">
          Every save creates a new version; older versions stay stored and every change is in the audit log.
          Text tools of the MCP server (anonymize_content …) use their own built-in policy unless ANONYMIZER_MCP_POLICY is set.
        </p>
      </div>
    </>
  );
}

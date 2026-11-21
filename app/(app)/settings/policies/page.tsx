import Link from "next/link";
import { SourceBanner } from "@/components/dashboard";
import { Chip, Collapsible } from "@/components/widgets";
import { getInfo, getMe, getPolicies, getPolicy, getSources } from "@/lib/anonymizer-api";
import { examplePolicyYaml } from "@/lib/mock";
import type { PolicyJson } from "@/lib/policy-edit";
import { cn } from "@/lib/utils";
import { PolicyEditor } from "./editor";

export const dynamic = "force-dynamic";

const apiUrl = () =>
  (process.env.ANONYMIZER_PUBLIC_API_URL || process.env.ANONYMIZER_API_URL || "https://anonymizer-api.example.com").replace(/\/$/, "");

const curl = (name: string) => `curl -X POST ${apiUrl()}/v1/policies/${encodeURIComponent(name)}/test \\
  -H "Authorization: Bearer $ANONYMIZER_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Herr Max Mustermann, max@example.org", "changes": {"email": "allow"}}'`;

export default async function Policies({ searchParams }: { searchParams: Promise<{ name?: string }> }) {
  const [{ data: policies, source }, { data: info }, { data: sources }, { data: me }] =
    await Promise.all([getPolicies(), getInfo(), getSources(), getMe()]);
  // Which part of OpenAnonymizer uses which policy, so it is clear what a change affects.
  const usedBy: Record<string, string[]> = {};
  const use = (name: string | null | undefined, what: string) => { if (name) (usedBy[name] ??= []).push(what); };
  use(info.default_policy, "Chat, API & MCP");
  use(sources.playground_policy ?? "support-default", "CSV uploads");
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
        {active && (
          <Collapsible title="Test via API" summary={`POST /v1/policies/${active.name}/test`}>
            <p className="text-muted-foreground text-xs">
              Same test as above, with any API key. Nothing is saved; <code>changes</code> is optional
              (action per data type, <code>null</code> = default).
            </p>
            <pre className="bg-surface-code overflow-auto rounded-md p-3 font-mono text-xs">{curl(active.name)}</pre>
            <p className="text-muted-foreground text-2xs">
              Response: <code>text_before</code>/<code>text_after</code> (null = not sent), <code>outcome_*</code>,
              {" "}<code>changes</code>, <code>entities</code>. See docs/policies.md.
            </p>
          </Collapsible>
        )}
        <Collapsible title="Versions and audit">
          <p className="text-muted-foreground text-xs">
            Every save creates a new version; older versions stay stored and every change is in the
            {" "}<Link className="text-link" href="/settings/audit-logs">audit log</Link>.
            A saved version applies right away to Chat, API and MCP (unless ANONYMIZER_MCP_POLICY pins a file for MCP).
          </p>
        </Collapsible>
      </div>
    </>
  );
}

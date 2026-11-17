import { PageHeader, TableScroll } from "@/components/app-shell";
import { SourceBanner } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getPolicies, getPolicy } from "@/lib/anonymizer-api";
import { examplePolicyYaml } from "@/lib/mock";

export const dynamic = "force-dynamic";

export default async function Policies() {
  const { data: policies, source } = await getPolicies();
  const active = policies.find(p => p.name === "legal-default") ?? policies[0];
  const detail = active ? await getPolicy(active.name) : null;
  const body = detail?.data ? JSON.stringify(detail.data, null, 2) : examplePolicyYaml;
  return (
    <>
      <PageHeader title="Policies" description="Deterministic · versioned · managed via API (admin key)" />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <Card><CardHeader><CardDescription>Policies</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={520}><Table><TableHeader><TableRow>
              <TableHead>Name</TableHead><TableHead>Version</TableHead><TableHead>Scope</TableHead><TableHead>Hash</TableHead>
            </TableRow></TableHeader>
              <TableBody>{policies.map(p => (
                <TableRow key={p.name}>
                  <TableCell className="font-medium">{p.name}</TableCell><TableCell>v{p.version}</TableCell>
                  <TableCell>{Object.entries(p.scope).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(", ") || "global"}</TableCell>
                  <TableCell className="font-mono">{p.hash.slice(0, 19)}…</TableCell>
                </TableRow>))}
              </TableBody></Table></TableScroll>
          </CardContent></Card>
        {active && <Card><CardHeader><CardDescription>{active.name} v{active.version}</CardDescription></CardHeader>
          <CardContent><pre className="bg-surface-code overflow-auto rounded-md p-4 font-mono text-xs">{body}</pre></CardContent></Card>}
        <p className="text-muted-foreground text-xs">
          New versions are created with <code>POST /v1/policies</code> or <code>anonymizer policy-validate</code> locally;
          test changes with <code>POST /v1/policies/dry-run</code>. A graphical editor is planned.
        </p>
      </div>
    </>
  );
}

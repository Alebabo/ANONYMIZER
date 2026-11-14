import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { policyYaml } from "@/lib/mock";

export default function Policies() {
  return (
    <>
      <PageHeader title="Policies" description="YAML editor · deterministic evaluation"><Button variant="outline" size="sm">Dry run</Button><Button size="sm">Save version</Button></PageHeader>
      <pre className="bg-surface-code m-6 overflow-auto rounded-md p-4 font-mono text-xs">{policyYaml}</pre>
    </>
  );
}

import { PageHeader, Badge } from "@/components/app-shell";
import { traceSteps } from "@/lib/mock";

export default async function Trace({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <PageHeader title={`Trace: ${id}`} description="POST /v1/chat/completions"><Badge>Processed</Badge></PageHeader>
      <div className="max-w-2xl space-y-4 p-4 md:p-6">
        <div className="text-muted-foreground flex gap-4 text-sm"><span>Original (restricted)</span><span className="text-foreground font-medium">Anonymized</span><span>Diff</span></div>
        <ol className="border-l pl-4">
          {traceSteps.map(([t, d]) => <li key={t} className="pb-4"><div className="text-sm font-medium">{t}</div><div className="text-muted-foreground text-xs">{d}</div></li>)}
        </ol>
        <p className="text-muted-foreground text-xs">Illustrative trace. Original content must remain protected and be hidden by default.</p>
      </div>
    </>
  );
}

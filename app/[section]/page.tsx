import { notFound } from "next/navigation";
import { PageHeader } from "@/components/app-shell";

const sections: Record<string, string> = { gateway: "Gateway", metrics: "Metrics", "api-keys": "API Keys", integrations: "Integrations", settings: "Settings" };

export default async function Section({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!sections[section]) notFound();
  return (<><PageHeader title={sections[section]} /><p className="text-muted-foreground p-6 text-sm">Not implemented yet. Planned for a later phase.</p></>);
}

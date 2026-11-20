import { PageHeader } from "@/components/app-shell";
import { SourceBanner } from "@/components/dashboard";
import { Collapsible } from "@/components/widgets";
import { getInfo, getPolicies } from "@/lib/anonymizer-api";
import { Chat } from "./chat";

export const dynamic = "force-dynamic";

const apiUrl = () =>
  (process.env.ANONYMIZER_PUBLIC_API_URL || process.env.ANONYMIZER_API_URL || "https://anonymizer-api.example.com").replace(/\/$/, "");

export default async function ChatPage() {
  const [{ data: policies, source }, { data: info }] = await Promise.all([getPolicies(), getInfo()]);
  const names = policies.map(p => p.name);
  const fallback = info.default_policy && names.includes(info.default_policy) ? info.default_policy : names[0] ?? "";
  const url = apiUrl();
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Chat" description="Test the model: type a text and see what an AI model receives. Every message is traced." />
      <SourceBanner source={source} />
      <Chat policies={names} defaultPolicy={fallback} />
      <div className="border-t px-4 py-2 md:px-6">
        <Collapsible title="Use the same model via API or MCP" className="mx-auto max-w-3xl border-0 bg-transparent">
          <p className="text-muted-foreground text-xs">API key from Settings → API Keys. Every call appears under Traces with channel and key.</p>
          <pre className="bg-surface-code overflow-auto rounded-md p-3 font-mono text-xs">{`# REST
curl -X POST ${url}/v1/protect \\
  -H "Authorization: Bearer $ANONYMIZER_API_KEY" -H "Content-Type: application/json" \\
  -d '{"text": "Herr Max Mustermann, max@example.org"}'

# MCP (Claude Code); tool: anonymize_content
claude mcp add --transport http anonymizer ${url}/mcp \\
  --header "Authorization: Bearer $ANONYMIZER_API_KEY"`}</pre>
        </Collapsible>
      </div>
    </div>
  );
}

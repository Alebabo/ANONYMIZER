import Link from "next/link";
import { PageHeader } from "@/components/app-shell";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export const dynamic = "force-dynamic";

type Integration = { id: string; title: string; what: string; lang: string; code: string; doc?: string };

function integrations(url: string): Integration[] {
  return [
    {
      id: "openai-python", title: "OpenAI SDK (Python)", lang: "python",
      what: "Existing OpenAI code: change base_url and use a OpenAnonymizer key. Every message is protected before it reaches the provider.",
      code: `from openai import OpenAI

client = OpenAI(base_url="${url}/v1", api_key="anonymizer_...")
client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Fasse das Schreiben von Herrn Mustermann zusammen ..."}],
)`,
      doc: "docs/gateway.md",
    },
    {
      id: "openai-node", title: "OpenAI SDK (TypeScript)", lang: "ts",
      what: "Same gateway from Node.js. Refused requests return HTTP 403 with error.type anonymizer_policy_violation.",
      code: `import OpenAI from "openai";

const client = new OpenAI({ baseURL: "${url}/v1", apiKey: process.env.ANONYMIZER_API_KEY });
await client.chat.completions.create({ model: "gpt-4o", messages: [{ role: "user", content: "..." }] });`,
    },
    {
      id: "sdk", title: "OpenAnonymizer Python SDK", lang: "python",
      what: "Direct access to protect, anonymize, scan and document protection.",
      code: `from anonymizer_sdk import OpenAnonymizer

anonymizer = OpenAnonymizer(api_key="anonymizer_...", base_url="${url}")
result = anonymizer.protect("Max Mustermann ist unser Mandant ...")
print(result.text if result.allowed else result.outcome)
anonymizer.protect_document("klage.docx").content   # anonymized DOCX`,
      doc: "sdk/python/README.md",
    },
    {
      id: "mcp", title: "MCP (Claude Desktop, Claude Code, Cursor)", lang: "json",
      what: "Local MCP server for agents: protected document access, no restore tool. Runs next to the client, not against this API.",
      code: `{
  "mcpServers": {
    "anonymizer": {
      "command": "anonymizer-mcp",
      "env": { "ANONYMIZER_MCP_ROOT": "/path/to/matter-folder", "ANONYMIZER_MCP_DESTINATION": "external" }
    }
  }
}`,
      doc: "docs/mcp.md",
    },
    {
      id: "mcp-http", title: "Remote MCP: customer chats & prompts (Claude Code, Cursor)", lang: "bash",
      what: "Agents read protected conversations and draft prompts through this API (ANONYMIZER_MCP_HTTP=1). One key per person: quota and audit log follow the key.",
      code: `claude mcp add --transport http anonymizer ${url}/mcp \\
  --header "Authorization: Bearer anonymizer_..."`,
      doc: "docs/conversations.md",
    },
    {
      id: "rest", title: "REST (curl)", lang: "bash",
      what: "Any language: POST text, get the policy outcome and the protected text.",
      code: `curl -s ${url}/v1/protect \\
  -H "Authorization: Bearer $ANONYMIZER_API_KEY" -H "Content-Type: application/json" \\
  -d '{"text":"Unser Mandant Herr Max Mustermann bittet um Rückruf.","destination":"external"}'`,
      doc: "docs/API.md",
    },
  ];
}

export default function Integrations() {
  const url = (process.env.ANONYMIZER_PUBLIC_API_URL ?? process.env.ANONYMIZER_API_URL ?? "https://anonymizer.example.com").replace(/\/$/, "");
  return (
    <>
      <PageHeader section="setup" title="Integrations" description="Connect applications and agents" />
      <div className="space-y-4 p-4 md:p-6">
        <p className="text-muted-foreground text-xs">
          Create a key under <Link className="text-link hover:text-link-hover" href="/api-keys">API Keys</Link> and replace{" "}
          <code>anonymizer_...</code>. Keys belong to your organization; traces of their requests appear in this workspace.
        </p>
        <div className="grid gap-4 xl:grid-cols-2">
          {integrations(url).map(i => (
            <Card key={i.id} id={i.id} className="min-w-0">
              <CardHeader>
                <h2 className="text-sm font-bold">{i.title}</h2>
                <CardDescription>{i.what}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <pre className="bg-surface-code overflow-x-auto rounded-md p-3 font-mono text-xs" aria-label={`${i.title} example (${i.lang})`}>{i.code}</pre>
                {i.doc && <p className="text-muted-foreground text-2xs">Reference: <code>{i.doc}</code></p>}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </>
  );
}

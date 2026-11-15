import Link from "next/link";
import { PageHeader, TableScroll } from "@/components/app-shell";
import { Notice, SourceBanner, Stat, fmt } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getConversationStats, getConversations, getQuota, getSources } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

export default async function Conversations({ searchParams }: { searchParams: Promise<{ cursor?: string }> }) {
  const { cursor } = await searchParams;
  const [{ data: page, source }, { data: stats }, { data: quota }, { data: sources }] = await Promise.all([
    getConversations(cursor), getConversationStats("prompt_version"), getQuota(), getSources()]);
  if (!page || !sources.conversations) {
    return (
      <>
        <PageHeader title="Conversations" description="Protected access to customer chat history" />
        <div className="space-y-4 p-4 md:p-6">
          <Notice>
            No conversation source is configured. Set <code>CATO_SOURCE</code> (jsonl, http or langfuse) on the API,
            see docs/conversations.md.
          </Notice>
        </div>
      </>
    );
  }
  const conv = sources.conversations;
  return (
    <>
      <PageHeader title="Conversations"
                  description={`${conv.kind} · ${conv.location} · policy ${sources.conversation_policy} · metadata only until opened`} />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:p-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Your reads today" value={quota ? `${fmt(quota.used)} / ${fmt(quota.limit)}` : "–"}
                sub="opening a conversation counts and is audited" />
          <Stat label="Conversations (scanned)" value={stats?.total != null ? fmt(stats.total) : `< ${conv.min_group}`}
                sub={stats?.truncated ? "scan limit reached" : "current source window"} />
          <Stat label="Minimum group size" value={`k = ${conv.min_group}`}
                sub={`${stats?.suppressed_groups ?? 0} small group(s) suppressed`} />
        </div>
        {stats && stats.groups.length > 0 && (
          <Card><CardHeader><CardDescription>By prompt version</CardDescription></CardHeader>
            <CardContent>
              <TableScroll minWidth={420}><Table><TableHeader><TableRow>
                <TableHead>Prompt</TableHead><TableHead className="text-right">Conversations</TableHead>
                <TableHead className="text-right">Messages</TableHead><TableHead className="text-right">Msg / conv.</TableHead>
              </TableRow></TableHeader>
                <TableBody>{stats.groups.map(g => (
                  <TableRow key={g.key}>
                    <TableCell className="font-mono">{g.key}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(g.conversations)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(g.messages)}</TableCell>
                    <TableCell className="text-right tabular-nums">{(g.messages / g.conversations).toFixed(1)}</TableCell>
                  </TableRow>))}
                </TableBody></Table></TableScroll>
            </CardContent></Card>
        )}
        <Card><CardHeader><CardDescription>Recent conversations</CardDescription></CardHeader>
          <CardContent>
            <TableScroll minWidth={640}><Table><TableHeader><TableRow>
              {["Conversation", "Day", "Messages", "Channel", "Tags", "Prompt"].map(h => <TableHead key={h}>{h}</TableHead>)}
            </TableRow></TableHeader>
              <TableBody>{page.data.map(c => (
                <TableRow key={c.id}>
                  <TableCell className="font-mono"><Link className="underline-offset-2 hover:underline" href={`/conversations/${c.id}`}>{c.id}</Link></TableCell>
                  <TableCell>{c.day}</TableCell>
                  <TableCell className="tabular-nums">{c.message_count ?? "–"}</TableCell>
                  <TableCell>{c.channel ?? "–"}</TableCell>
                  <TableCell>{c.tags.join(", ") || "–"}</TableCell>
                  <TableCell className="font-mono">{c.prompt ? `${c.prompt}${c.prompt_version != null ? `@${c.prompt_version}` : ""}` : "–"}</TableCell>
                </TableRow>))}
                {!page.data.length && <TableRow><TableCell colSpan={6} className="text-muted-foreground py-6 text-center">No conversations</TableCell></TableRow>}
              </TableBody></Table></TableScroll>
            {page.next_cursor && (
              <div className="mt-3 text-right text-sm">
                <Link className="underline-offset-2 hover:underline" href={`/conversations?cursor=${encodeURIComponent(page.next_cursor)}`}>Next page →</Link>
              </div>
            )}
          </CardContent></Card>
        <p className="text-muted-foreground text-xs">
          Source ids never leave Cato; the ids shown here are opaque. Tags or prompt names that contain detectable data are dropped.
          {sources.mcp_http ? " Agents use the same data through the MCP endpoint /mcp with their own API key and quota." : ""}
        </p>
      </div>
    </>
  );
}

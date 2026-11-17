import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/app-shell";
import { Notice, Pill, SourceBanner } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { ApiError, getConversation } from "@/lib/anonymizer-api";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function ConversationDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let result;
  try {
    result = await getConversation(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 429) {
      return (
        <>
          <PageHeader title={`Conversation ${id}`} description="Daily limit reached" />
          <div className="p-4 md:p-6"><Notice>{e.message}. The limit resets at 00:00 UTC.</Notice></div>
        </>
      );
    }
    throw e;
  }
  const { data: c, source } = result;
  if (!c) notFound();
  return (
    <>
      <PageHeader title={`Conversation ${c.id}`}
                  description={`${c.day} · ${c.message_count ?? c.messages.length} messages · ${c.channel ?? "–"} · ${c.prompt ?? "no prompt"}${c.prompt_version != null ? `@${c.prompt_version}` : ""}`}>
        <Pill value={c.outcome} />
      </PageHeader>
      <SourceBanner source={source} />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader><CardDescription>Messages (protected)</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {c.messages.map((m, i) => (
              <div key={i} className={cn("max-w-[85%] rounded-md px-3 py-2 text-sm", m.role === "user" ? "bg-muted" : "bg-light-blue ml-auto")}>
                <div className="text-muted-foreground mb-1 flex justify-between gap-3 text-2xs uppercase tracking-wide">
                  <span>{m.role}</span>{m.minute != null && <span>+{m.minute} min</span>}
                </div>
                {m.content != null
                  ? <p className="whitespace-pre-wrap break-words">{m.content}</p>
                  : <p className="text-dark-red text-xs">Withheld by policy ({m.outcome ?? "review"}): {m.reason}</p>}
              </div>))}
            {c.truncated && <Notice>Only the first {c.messages.length} messages are shown.</Notice>}
          </CardContent></Card>
        <Card><CardHeader><CardDescription>Decision</CardDescription></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Outcome</span><Pill value={c.outcome} /></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Risk</span><Pill value={c.risk} /></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Withheld</span><span>{c.withheld}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Tags</span><span>{c.tags.join(", ") || "–"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Your reads today</span><span>{c.quota.used} / {c.quota.limit}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Trace</span>
              <Link className="font-mono underline-offset-2 hover:underline" href={`/traces/${c.trace_id}`}>{c.trace_id}</Link></div>
            <p className="text-muted-foreground pt-2 text-xs">
              {c.stable_placeholders
                ? "Placeholders are stable for this conversation; an admin can restore them with the vault (POST /v1/restore, namespace conversation:<id>)."
                : "No vault configured: placeholders are generated per read and cannot be restored."}
            </p>
          </CardContent></Card>
      </div>
    </>
  );
}

import Link from "next/link";
import { PageHeader } from "@/components/app-shell";
import { Distribution, Pill, SourceBanner, Stat, fmt, pct } from "@/components/dashboard";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { getGateway, getMetrics, type GatewayStatus } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

function UpstreamCard({ title, up, note }: { title: string; up: GatewayStatus["external"]; note: string }) {
  return (
    <Card><CardHeader className="flex-row items-center justify-between space-y-0"><CardDescription>{title}</CardDescription>
      <Pill value={up ? "configured" : "not configured"} /></CardHeader>
      <CardContent>
        {up ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">Host</dt><dd className="font-mono break-all">{up.host}</dd>
            <dt className="text-muted-foreground">Provider</dt><dd>{up.provider}</dd>
            <dt className="text-muted-foreground">Model</dt><dd>{up.model ?? "from request"}</dd>
            <dt className="text-muted-foreground">Credential</dt><dd>{up.authenticated ? "set (server-side)" : "none"}</dd>
          </dl>
        ) : <p className="text-muted-foreground text-xs">{note}</p>}
      </CardContent></Card>
  );
}

export default async function Gateway() {
  const [{ data: g, source }, { data: m }] = await Promise.all([getGateway(), getMetrics(24)]);
  const gw = m.by_route["/v1/chat/completions"] ?? 0;
  const local = m.by_provider.local ?? 0;
  return (
    <>
      <PageHeader section="setup" title="Gateway" description={`OpenAI-compatible · POST ${g.endpoint}`} />
      <SourceBanner source={source} />
      <div className="space-y-4 p-4 md:space-y-6 md:p-6">
        <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          <Stat label="Gateway requests (24 h)" value={fmt(gw)} sub={`${pct(m.requests ? gw / m.requests : 0)} of all requests`} />
          <Stat label="Routed to local model" value={fmt(local)} sub="local_only content" />
          <Stat label="Refused" value={fmt((m.by_outcome.review ?? 0) + (m.by_outcome.block ?? 0))} sub="review / block" />
          <Stat label="Latency p95" value={m.latency_ms.p95 != null ? `${fmt(Math.round(m.latency_ms.p95))} ms` : "–"}
                sub={`avg ${m.latency_ms.avg != null ? `${fmt(Math.round(m.latency_ms.avg))} ms` : "–"}`} />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <UpstreamCard title="External provider" up={g.external} note="Set ANONYMIZER_UPSTREAM_URL and ANONYMIZER_UPSTREAM_KEY on the API server." />
          <UpstreamCard title="Local model" up={g.local}
                        note="Optional. Set ANONYMIZER_LOCAL_UPSTREAM_URL (e.g. Ollama) so local_only content is answered locally instead of refused." />
          <Card><CardHeader><CardDescription>Behaviour</CardDescription></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                <dt className="text-muted-foreground">Policy</dt><dd>{g.default_policy} (or scope resolution)</dd>
                <dt className="text-muted-foreground">Restore answers</dt><dd>{g.restore_responses ? "yes, placeholders → originals" : "no, placeholders returned"}</dd>
                <dt className="text-muted-foreground">Streaming</dt><dd>{g.streaming ? "supported" : "not supported yet"}</dd>
                <dt className="text-muted-foreground">Timeout</dt><dd>{g.timeout_s} s</dd>
              </dl>
            </CardContent></Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card><CardHeader><CardDescription>Providers (24 h)</CardDescription></CardHeader>
            <CardContent><Distribution data={m.by_provider} empty="No provider traffic yet" /></CardContent></Card>
          <Card><CardHeader><CardDescription>Request flow</CardDescription></CardHeader>
            <CardContent>
              <ol className="list-decimal space-y-1.5 pl-4 text-xs">
                <li>Collect text from messages and tool-call arguments (images and audio are refused).</li>
                <li>Protect every message with the active policy; one in-memory vault per request keeps placeholders consistent.</li>
                <li>Most restrictive outcome wins: <b>allow</b> → provider, <b>local_only</b> → local model, <b>review/block</b> → HTTP 403.</li>
                <li>Restore placeholders in the answer and record a metadata-only trace.</li>
              </ol>
            </CardContent></Card>
        </div>
        <p className="text-muted-foreground text-xs">
          Upstream settings are environment variables on the API server, so provider keys never leave it.
          Client setup: <Link className="text-link hover:text-link-hover" href="/integrations">Integrations</Link>.
        </p>
      </div>
    </>
  );
}

import { ApiError, apiText, isDemo } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

/** Download of GET /v1/feedback/export for admins; the session token stays on the server. */
export async function GET() {
  if (isDemo()) return new Response("Demo mode: no feedback stored.\n", { status: 404 });
  try {
    const body = await apiText("/v1/feedback/export");
    return new Response(body, {
      headers: { "Content-Type": "application/x-ndjson; charset=utf-8",
                 "Content-Disposition": 'attachment; filename="feedback.jsonl"' },
    });
  } catch (e) {
    if (e instanceof ApiError) return new Response(e.message, { status: e.status });
    throw e;
  }
}

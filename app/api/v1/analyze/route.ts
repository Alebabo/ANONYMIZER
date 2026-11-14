import { NextRequest, NextResponse } from "next/server";
import { analyzeText } from "@/lib/privacy-engine";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_TEXT_LENGTH = 100_000;

export async function POST(request: NextRequest) {
  try {
    const body: unknown = await request.json();
    if (!body || typeof body !== "object" || !("text" in body) || typeof body.text !== "string") {
      return NextResponse.json({ error: "Request body must contain a text string." }, { status: 400 });
    }
    const text = body.text;
    if (!text.trim()) return NextResponse.json({ error: "Text must not be empty." }, { status: 400 });
    if (text.length > MAX_TEXT_LENGTH) return NextResponse.json({ error: "Text exceeds the 100000 character limit." }, { status: 413 });
    return NextResponse.json(analyzeText(text), { headers: { "Cache-Control": "no-store, max-age=0", "X-Content-Type-Options": "nosniff" } });
  } catch {
    return NextResponse.json({ error: "Invalid JSON request." }, { status: 400 });
  }
}

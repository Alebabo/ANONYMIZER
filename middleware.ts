import { NextResponse, type NextRequest } from "next/server";

/**
 * Optional HTTP Basic Auth for the dashboard (CATO_DASHBOARD_USER / CATO_DASHBOARD_PASSWORD).
 * Live API data is only shown when this is configured (see lib/cato-api.ts).
 * Use HTTPS (Vercel does by default); put SSO in front for production teams.
 */
export function middleware(req: NextRequest) {
  const user = process.env.CATO_DASHBOARD_USER;
  const password = process.env.CATO_DASHBOARD_PASSWORD;
  if (!user || !password) return NextResponse.next();

  const header = req.headers.get("authorization") ?? "";
  if (header.startsWith("Basic ")) {
    const [u, ...rest] = atob(header.slice(6)).split(":");
    if (safeEqual(u, user) && safeEqual(rest.join(":"), password)) return NextResponse.next();
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Cato", charset="UTF-8"' },
  });
}

function safeEqual(a: string, b: string): boolean {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

export const config = { matcher: ["/((?!_next/static|_next/image|icon.svg|brand/).*)"] };

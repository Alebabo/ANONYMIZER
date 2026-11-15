import { NextResponse, type NextRequest } from "next/server";

/**
 * Login gate. With CATO_API_URL set (live mode) every page except /login requires a session
 * cookie; the API validates the token on each call and expired sessions are sent back to /login.
 * Without CATO_API_URL the dashboard runs in demo mode with example data and no login.
 */
const COOKIE = "cato_session";

export function middleware(req: NextRequest) {
  if (!process.env.CATO_API_URL) return NextResponse.next();
  const { pathname, search } = req.nextUrl;
  const hasSession = Boolean(req.cookies.get(COOKIE)?.value);
  if (pathname === "/login") return NextResponse.next();
  if (!hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|icon.svg|brand/).*)"] };

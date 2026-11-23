import { NextResponse, type NextRequest } from "next/server";

/**
 * Login gate. With ANONYMIZER_API_URL set (live mode) every page except /login requires a session
 * cookie; the API validates the token on each call and expired sessions are sent back to /login.
 * Without ANONYMIZER_API_URL the dashboard runs in demo mode with example data and no login.
 */
const COOKIE = "anonymizer_session";

export function middleware(req: NextRequest) {
  if (!process.env.ANONYMIZER_API_URL) return NextResponse.next();
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

// Icons and the manifest stay public: the browser fetches them before login (taskbar icon of the app window).
export const config = { matcher: ["/((?!_next/static|_next/image|icon\\.svg|icon1\\.png|manifest\\.webmanifest|brand/).*)"] };

/**
 * Keep signed-out visitors on the login page.
 *
 * The session is an HttpOnly cookie, so this runs on the server, where it can
 * see it. It checks only that a session exists: whether it is still valid is
 * the API's decision, made on every request, and an expired one is answered
 * with a 401 that sends the browser back here. Deep links survive sign-in.
 */
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  if (pathname === "/login") return NextResponse.next();
  if (!signedIn) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Pages only: the API proxy, Next's assets and static files are not pages.
  matcher: ["/((?!api/|_next/|icon\\.svg|favicon\\.ico|robots\\.txt).*)"],
};

/**
 * The browser session is an HttpOnly cookie set by the API on sign-in. Scripts
 * on the page cannot read it; only the server (the proxy, and the middleware
 * that keeps signed-out visitors on the login page) ever sees it.
 */
export const SESSION_COOKIE = "textileops_session";

/** Sent on every web request. The API requires it on cookie-authenticated writes (CSRF). */
export const CLIENT_HEADER = "x-textileops-client";

/**
 * Where to go after signing in: the page the visitor was sent here from, if it
 * is a path on this site. Anything else — another host, a protocol-relative
 * "//evil.example" — goes to the Command Centre instead.
 */
export function safeNext(search: string): string {
  const next = new URLSearchParams(search).get("next");
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  return next;
}

/**
 * Same-origin proxy to the TextileOps API.
 *
 * In a deployment the browser calls `/api/v1/...` on the web origin and this
 * handler forwards it to `API_ORIGIN`, read at request time on the server. That
 * gives three things at once:
 *
 *  - no CORS, because the browser only ever talks to one origin;
 *  - no build-time API URL, so one web image runs against any API;
 *  - nothing about the API's location, or anything secret, in the bundle. The
 *    model provider's key lives only in the API's environment and is never
 *    visible to this process either.
 *
 * The target origin comes from server configuration only. Nothing in the
 * request can change the host it is sent to.
 */
import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const FORWARD_REQUEST_HEADERS = ["authorization", "content-type", "accept", "x-request-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "x-request-id", "content-disposition", "cache-control"];

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  // API_ORIGIN is a full URL. API_HOSTPORT is what a platform's private network
  // hands out ("textileops-api:10000"); it is plain HTTP inside that network.
  const origin =
    process.env.API_ORIGIN || (process.env.API_HOSTPORT ? `http://${process.env.API_HOSTPORT}` : "");
  if (!origin) {
    return Response.json(
      {
        code: "api_not_configured",
        message: "The web app has no API_ORIGIN configured, so it cannot reach the TextileOps API.",
      },
      { status: 502 },
    );
  }
  const { path } = await context.params;
  const target = new URL(`/api/v1/${path.map(encodeURIComponent).join("/")}`, origin);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Required by Node's fetch to stream a request body (uploads).
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
    } as RequestInit);
  } catch {
    return Response.json(
      { code: "api_unreachable", message: "The TextileOps API could not be reached. It may be starting up — try again in a moment." },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

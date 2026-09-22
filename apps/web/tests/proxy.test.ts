// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/v1/[...path]/route";

/**
 * The same-origin proxy is the only way a deployed browser reaches the API,
 * so its guarantees are tested directly: it goes where configuration says and
 * nowhere else, it forwards identity, and it says so plainly when it cannot.
 */

const params = (...path: string[]) => ({ params: Promise.resolve({ path }) });

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("API proxy", () => {
  it("refuses with a clear message when no API origin is configured", async () => {
    vi.stubEnv("API_ORIGIN", "");
    const response = await GET(new NextRequest("http://web.example/api/v1/health"), params("health"));
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("api_not_configured");
  });

  it("forwards to the configured origin with the caller's token and query", async () => {
    vi.stubEnv("API_ORIGIN", "https://api.internal.example");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const request = new NextRequest("http://web.example/api/v1/orders?risk=late", {
      headers: { authorization: "Bearer abc", cookie: "other=should-not-travel; textileops_session=tok" },
    });
    const response = await GET(request, params("orders"));
    expect(response.status).toBe(200);
    const [target, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(target)).toBe("https://api.internal.example/api/v1/orders?risk=late");
    const sent = new Headers(init.headers);
    expect(sent.get("authorization")).toBe("Bearer abc");
    // Only an allow-list of headers is forwarded, and of the cookies only the
    // session travels: nothing else set on this origin reaches the API.
    expect(sent.get("cookie")).toBe("textileops_session=tok");
  });

  it("accepts a private-network host:port when no full origin is given", async () => {
    vi.stubEnv("API_ORIGIN", "");
    vi.stubEnv("API_HOSTPORT", "textileops-api:10000");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await GET(new NextRequest("http://web.example/api/v1/health"), params("health"));
    const [target] = fetchMock.mock.calls[0] as [URL];
    expect(String(target)).toBe("http://textileops-api:10000/api/v1/health");
  });

  it("cannot be steered to another host by the path", async () => {
    vi.stubEnv("API_ORIGIN", "https://api.internal.example");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await GET(new NextRequest("http://web.example/api/v1/x"), params("//evil.example", "..", "health"));
    const [target] = fetchMock.mock.calls[0] as [URL];
    expect(new URL(String(target)).host).toBe("api.internal.example");
  });

  it("passes the API's status through, errors included", async () => {
    vi.stubEnv("API_ORIGIN", "https://api.internal.example");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ code: "auth_error" }), { status: 401, headers: { "content-type": "application/json" } }),
    );
    const response = await POST(
      new NextRequest("http://web.example/api/v1/auth/login", { method: "POST", body: "{}" }),
      params("auth", "login"),
    );
    expect(response.status).toBe(401);
  });

  it("reports an unreachable API as such, not as a crash", async () => {
    vi.stubEnv("API_ORIGIN", "https://api.internal.example");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const response = await GET(new NextRequest("http://web.example/api/v1/health"), params("health"));
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("api_unreachable");
  });

  it("passes the session cookie back to the browser, and nothing else the API sets", async () => {
    vi.stubEnv("API_ORIGIN", "https://api.internal.example");
    const upstream = new Headers({ "content-type": "application/json" });
    upstream.append("set-cookie", "textileops_session=tok; HttpOnly; Path=/; SameSite=lax");
    upstream.append("set-cookie", "tracking=1; Path=/");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200, headers: upstream }));
    const response = await POST(new NextRequest("http://web.example/api/v1/auth/demo-login", { method: "POST" }), params("auth", "demo-login"));
    expect(response.headers.getSetCookie()).toEqual(["textileops_session=tok; HttpOnly; Path=/; SameSite=lax"]);
  });
});

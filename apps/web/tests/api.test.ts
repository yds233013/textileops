import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, clearSession, getToken, setSession } from "@/lib/api";

describe("apiFetch", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => clearSession());

  it("stores and reads a session", () => {
    setSession("token-123", { id: "1", full_name: "Ops" });
    expect(getToken()).toBe("token-123");
    clearSession();
    expect(getToken()).toBeNull();
  });

  it("sends the bearer token when one is stored", async () => {
    setSession("token-123", {});
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/dashboard");
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer token-123");
  });

  it("puts query parameters on the URL and drops empty ones", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("[]", { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/orders", { query: { risk: "at_risk", search: "", limit: 10 } });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("risk=at_risk");
    expect(url).toContain("limit=10");
    expect(url).not.toContain("search=");
  });

  it("surfaces the API's own error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "validation_error",
            message: "Closing an exception requires a note.",
            details: {},
          }),
          { status: 422, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(apiFetch("/exceptions/x/status", { body: {} })).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Closing an exception requires a note.",
    });
  });

  it("clears the session on a 401", async () => {
    setSession("stale", {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    await expect(apiFetch("/dashboard")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
  });
});

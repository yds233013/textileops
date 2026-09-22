import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, forgetUser, getStoredUser, rememberUser } from "@/lib/api";

describe("apiFetch", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => forgetUser());

  it("keeps no credential in page storage", () => {
    // Left behind by an earlier version that stored the token here.
    window.localStorage.setItem("textileops.token", "leftover");
    rememberUser({ id: "1", full_name: "Ops" });
    expect(getStoredUser()).toEqual({ id: "1", full_name: "Ops" });
    expect(window.localStorage.getItem("textileops.token")).toBeNull();
    expect(JSON.stringify({ ...window.localStorage })).not.toMatch(/token|eyJ/);
  });

  it("sends the cookie and identifies itself, and never a bearer header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/dashboard");
    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe("include");
    expect(init.headers["x-textileops-client"]).toBe("web");
    expect(init.headers.Authorization).toBeUndefined();
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

  it("forgets the signed-in person on a 401", async () => {
    rememberUser({ id: "1" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    await expect(apiFetch("/dashboard")).rejects.toBeInstanceOf(ApiError);
    expect(getStoredUser()).toBeNull();
  });
});

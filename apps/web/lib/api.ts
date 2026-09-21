/**
 * Typed client for the TextileOps API.
 *
 * The access token lives in localStorage and is sent as a bearer header. There
 * are no secrets in the browser: the API key for the model provider never
 * leaves the server.
 */

/**
 * Where the browser sends API calls. By default the same origin (`/api/v1`),
 * which the web server proxies to the API — see app/api/v1/[...path]/route.ts.
 * Set NEXT_PUBLIC_API_BASE_URL to talk to an API directly (local development).
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

const TOKEN_KEY = "textileops.token";
const USER_KEY = "textileops.user";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: unknown): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser<T>(): T | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(
    `${API_BASE}${path}`,
    typeof window !== "undefined" ? window.location.origin : "http://localhost",
  );
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(url.toString(), {
    method: options.method ?? (options.body || options.formData ? "POST" : "GET"),
    headers,
    body: options.formData ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    signal: options.signal,
  });

  if (response.status === 401 && typeof window !== "undefined") {
    clearSession();
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status}).`;
    let details: Record<string, unknown> = {};
    try {
      const payload = await response.json();
      code = payload.code ?? code;
      message = payload.message ?? message;
      details = payload.details ?? {};
    } catch {
      /* the body was not JSON; the default message stands */
    }
    throw new ApiError(response.status, code, message, details);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  login: (email: string, password: string) =>
    apiFetch<{ access_token: string; user: unknown }>("/auth/login", {
      body: { email, password },
    }),
  me: () => apiFetch("/auth/me"),
  demoInfo: () =>
    apiFetch<{ enabled: boolean; email: string | null; full_name: string | null; role: string | null }>(
      "/auth/demo",
    ),
  demoLogin: () =>
    apiFetch<{ access_token: string; user: unknown }>("/auth/demo-login", { method: "POST" }),
  health: () => apiFetch("/health"),
};

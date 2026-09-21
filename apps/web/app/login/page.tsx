"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setSession } from "@/lib/api";
import { Button, Field, inputClass } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("owner@kaveriknits.example");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [demo, setDemo] = useState<{ enabled: boolean; full_name: string | null } | null>(null);

  useEffect(() => {
    api.demoInfo().then(setDemo).catch(() => setDemo(null));
  }, []);

  async function enterDemo() {
    setPending(true);
    setError(null);
    try {
      const result = await api.demoLogin();
      setSession(result.access_token, result.user);
      router.replace("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
      setPending(false);
    }
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await api.login(email, password);
      setSession(result.access_token, result.user);
      router.replace("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-950">TextileOps</h1>
          <p className="mt-1 text-sm text-ink-600">
            Operations control for Kaveri Knit Fabrics.
          </p>
        </div>
        {demo?.enabled && (
          <Button type="button" variant="primary" onClick={enterDemo} disabled={pending}>
            Explore the demo
          </Button>
        )}
        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-lg border border-ink-200 bg-white p-5 shadow-sm"
        >
          <Field label="Email" htmlFor="email">
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Password" htmlFor="password">
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className={inputClass}
            />
          </Field>
          {error && (
            <p
              role="alert"
              className="rounded border border-critical-border bg-critical-bg px-2.5 py-1.5 text-sm text-critical-text"
            >
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={pending}>
            {pending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        <p className="mt-4 text-center text-xs text-ink-500">
          Seeded development accounts use the password set in <code>DEMO_PASSWORD</code>{" "}
          (<code>textileops</code> by default).
        </p>
      </div>
    </main>
  );
}

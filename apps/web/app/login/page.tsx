"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { IconArrowRight, Logo } from "@/components/icons";
import { Button, Field, inputClass } from "@/components/ui";
import { api, isStartingUp, rememberUser } from "@/lib/api";
import { WakingUp } from "@/components/waking";
import { safeNext } from "@/lib/session";

type Demo = { enabled: boolean; full_name: string | null } | null;

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<"password" | "demo" | null>(null);
  const [demo, setDemo] = useState<Demo>(null);
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    document.title = "Sign in · TextileOps";
    let cancelled = false;
    let retry: number | undefined;
    const load = () =>
      api
        .demoInfo()
        .then((value) => {
          if (cancelled) return;
          setWaking(false);
          setDemo(value);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          if (isStartingUp(err)) {
            // Free hosting waking from sleep: say so, and keep asking.
            setWaking(true);
            retry = window.setTimeout(load, 3000);
          } else {
            setDemo(null);
          }
        });
    load();
    return () => {
      cancelled = true;
      window.clearTimeout(retry);
    };
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending("password");
    setError(null);
    try {
      const result = await api.login(email, password);
      rememberUser(result.user);
      router.replace(safeNext(window.location.search));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setPending(null);
    }
  }

  async function enterDemo() {
    setPending("demo");
    setError(null);
    try {
      const result = await api.demoLogin();
      rememberUser(result.user);
      router.replace(safeNext(window.location.search));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
      setPending(null);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      {/* The pitch: what this is, in the words of the person who would use it. */}
      <section className="relative hidden flex-col justify-between overflow-hidden bg-ink-950 px-12 py-10 text-white lg:flex">
        <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.07]" style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, #fff 0 1px, transparent 1px 14px), repeating-linear-gradient(90deg, #fff 0 1px, transparent 1px 14px)",
        }} />
        <div className="relative flex items-center gap-2.5">
          <Logo size={28} />
          <span className="text-[15px] font-semibold tracking-tight">TextileOps</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-[28px] font-semibold leading-9 tracking-[-0.015em]">
            Know which orders will be late before your customers do.
          </h1>
          <p className="mt-4 text-[15px] leading-6 text-ink-300">
            TextileOps watches orders, yarn, purchase orders, production, QC and shipments, and
            answers four questions all day: what needs attention, why, what it costs if nothing
            changes, and what to do next.
          </p>
          <ul className="mt-8 space-y-3 text-[13.5px] text-ink-300">
            {[
              "Every figure is calculated from your records — never by a model.",
              "Supplier emails and documents are read, but treated as untrusted.",
              "AI can investigate and propose. Only a person can approve.",
            ].map((line) => (
              <li key={line} className="flex gap-2.5">
                <span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-300" />
                {line}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-ink-500">Operations control for textile manufacturers.</p>
      </section>

      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-2.5">
              <Logo size={28} />
              <span className="text-[15px] font-semibold tracking-tight text-ink-950">TextileOps</span>
            </div>
            {/* On a phone the pitch panel is hidden; this is the one line of it that must survive. */}
            <p className="mt-3 text-[13.5px] leading-5 text-ink-600">
              AI-assisted production and order control for textile manufacturers: it reconciles orders,
              yarn, purchasing, production, QC and shipments, and flags what will make an order late.
            </p>
          </div>

          <h2 className="text-xl font-semibold tracking-tight text-ink-950">Sign in</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">Kaveri Knit Fabrics</p>

          {waking && (
            <div className="mt-6">
              <WakingUp compact />
            </div>
          )}

          {demo?.enabled && (
            <div className="mt-6 rounded-lg border border-brand-200 bg-brand-50 p-4">
              <p className="text-[13.5px] font-medium text-brand-900">Take the guided demo</p>
              <p className="mt-1 text-[13px] leading-5 text-brand-800/80">
                A fictional knitting mill with a supplier running late, a failed shade check and
                decisions waiting for approval. No password needed
                {demo.full_name ? ` — you will be signed in as ${demo.full_name}, the owner` : ""}.
              </p>
              <p className="mt-1.5 text-xs leading-5 text-brand-800/70">
                Approve, dismiss, upload — anything you change is put back once the demo has been left
                alone for a while, so the next visitor sees the same story.
              </p>
              <div className="mt-3">
                <Button
                  variant="primary"
                  size="lg"
                  onClick={enterDemo}
                  loading={pending === "demo"}
                  disabled={pending !== null}
                  icon={pending === "demo" ? undefined : <IconArrowRight size={15} />}
                >
                  Explore the demo
                </Button>
              </div>
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            {demo?.enabled && (
              <div className="flex items-center gap-3 text-xs text-ink-400">
                <span className="h-px flex-1 bg-ink-150" />
                or sign in with an account
                <span className="h-px flex-1 bg-ink-150" />
              </div>
            )}
            <Field label="Email" htmlFor="email">
              <input
                id="email"
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className={inputClass}
                placeholder="you@company.com"
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
              <p role="alert" className="rounded-md border border-critical-border bg-critical-bg px-3 py-2 text-[13px] text-critical-text">
                {error}
              </p>
            )}
            <Button type="submit" variant={demo?.enabled ? "secondary" : "primary"} loading={pending === "password"} disabled={pending !== null}>
              Sign in
            </Button>
          </form>
        </div>
      </section>
    </main>
  );
}

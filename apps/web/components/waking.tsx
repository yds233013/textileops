"use client";

import { useEffect, useState } from "react";
import { Logo } from "@/components/icons";

/**
 * Shown while the API is still starting. The hosted demo runs on free hosting
 * that sleeps when nobody is using it; waking it takes a minute or two, and a
 * visitor should be told that plainly rather than shown an error or a blank
 * page. Whoever shows this keeps retrying and moves on by itself.
 */
export function WakingUp({ compact = false }: { compact?: boolean }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const body = (
    <div role="status" aria-live="polite" className="rounded-lg border border-brand-200 bg-brand-50 p-4">
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="h-2.5 w-2.5 animate-pulse rounded-full bg-brand-500" />
        <p className="text-[13.5px] font-medium text-brand-900">Waking TextileOps up…</p>
      </div>
      <p className="mt-1.5 text-[13px] leading-5 text-brand-800/80">
        This demo runs on free hosting, which goes to sleep when nobody is using it. Waking it takes
        about a minute. This page carries on by itself.
      </p>
      {seconds >= 5 && <p className="mt-1.5 text-xs text-brand-800/60 tnum">Waiting {seconds} s</p>}
    </div>
  );
  if (compact) return body;
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <Logo size={28} />
          <span className="text-[15px] font-semibold tracking-tight text-ink-950">TextileOps</span>
        </div>
        {body}
      </div>
    </div>
  );
}

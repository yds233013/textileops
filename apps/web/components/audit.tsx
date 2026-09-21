"use client";

import type { AuditEvent } from "@/lib/types";

/** Who did it: a person, the deterministic engine, the system, or a model. */
export function ActorTag({ event }: { event: AuditEvent }) {
  const label =
    event.actor_type === "user"
      ? "Person"
      : event.actor_type === "ai"
        ? "AI"
        : event.actor_label === "exception-engine"
          ? "Engine"
          : "System";
  const cls =
    event.actor_type === "user"
      ? "bg-brand-50 text-brand-800 ring-brand-200"
      : event.actor_type === "ai"
        ? "bg-ai-bg text-ai-text ring-ai-border"
        : "bg-ink-50 text-ink-600 ring-ink-200";
  return (
    <span className={`w-16 shrink-0 rounded px-1.5 py-[1px] text-center text-2xs font-semibold ring-1 ring-inset ${cls}`}>
      {label}
    </span>
  );
}

"use client";

import type { AuditEvent } from "@/lib/types";

/** Who did it: a named person, the exception engine, the system, or an investigation. */
export function actorName(event: AuditEvent): string {
  if (event.actor_type === "user") return event.actor_name ?? "A person";
  if (event.actor_type === "ai") {
    return event.actor_label === "deterministic-rules-v1" || !event.actor_label
      ? "Investigation (rule engine)"
      : `Investigation (${event.actor_label})`;
  }
  if (event.actor_label === "exception-engine") return "Exception engine";
  return "TextileOps";
}

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

const ACTION_LABEL: Record<string, string> = {
  "exception.detected": "Exception raised",
  "exception.investigated": "Investigated",
  "exception.status_changed": "Exception closed",
  "proposal.created": "Action proposed",
  "proposal.approved": "Approved",
  "proposal.rejected": "Rejected",
  "action.executed": "Carried out",
  "purchase_order.received": "Goods received",
  "purchase_order.eta_revised": "Delivery date moved",
  "purchase_order.receipt_corrected": "Receipt corrected",
  "production.started": "Batch started",
  "production.output_recorded": "Output recorded",
  "production.completed": "Batch completed",
  "production.rework_scheduled": "Replacement scheduled",
  "production.qc_outcome_applied": "QC applied to batch",
  "qc.recorded": "Inspection recorded",
  "message.received": "Message received",
  "document.received": "Document received",
  "document.processed": "Document read",
  "shipment.dispatched": "Dispatched",
  "shipment.delivered": "Arrival confirmed",
  "reconciliation.resolved": "Review resolved",
  "reconciliation.dismissed": "Review dismissed",
};

export function actionLabel(action: string): string {
  if (ACTION_LABEL[action]) return ACTION_LABEL[action];
  const tail = action.split(".").pop() ?? action;
  const spaced = tail.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

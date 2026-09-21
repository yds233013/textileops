"use client";

import { daysFromNow, shortDate } from "@/lib/format";
import { statusLabel } from "@/lib/labels";
import type { OrderSummary } from "@/lib/types";
import { READINESS_TONE, type Tone } from "./ui";

const SEGMENT: Record<Tone, string> = {
  ok: "bg-good-solid",
  warn: "bg-medium-solid",
  bad: "bg-critical-solid",
  info: "bg-info-solid",
  neutral: "bg-ink-200",
};

/**
 * The four stages an order passes through, as one strip: material,
 * production, QC, shipment. Each segment carries the same tone the status pill
 * would, so red here and red on the detail page mean the same thing. The text
 * is always available to assistive technology and on hover.
 */
export function OrderPipeline({ order }: { order: OrderSummary }) {
  const stages: [string, string][] = [
    ["Materials", order.material_readiness],
    ["Production", order.production_status],
    ["QC", order.qc_status],
    ["Shipment", order.shipment_status],
  ];
  const description = stages.map(([name, value]) => `${name}: ${statusLabel(value)}`).join(", ");
  return (
    <div className="w-28" title={description} aria-label={description} role="img">
      <div className="flex gap-0.5">
        {stages.map(([name, value]) => (
          <span key={name} className={`h-1.5 flex-1 rounded-full ${SEGMENT[READINESS_TONE[value] ?? "neutral"]}`} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-2xs text-ink-400">
        {stages.map(([name]) => (
          <span key={name}>{name === "Materials" ? "Mat" : name === "Production" ? "Prod" : name === "Shipment" ? "Ship" : name}</span>
        ))}
      </div>
    </div>
  );
}

/**
 * When the order will be finished, stated no more confidently than the data
 * allows. A forecast date already in the past for work that is still open is
 * not a forecast — it is an overdue plan with no revised date, and says so.
 */
export function forecast(order: {
  estimated_completion: string | null;
  completion_unknown_reason: string | null;
  days_ahead: number | null;
  status?: string;
}): { value: string; hint: string; tone: "ok" | "warn" | "bad" | "neutral" } {
  if (order.estimated_completion) {
    const until = daysFromNow(order.estimated_completion);
    if (until !== null && until < 0) {
      return {
        value: "Overdue",
        hint: `plan said ${shortDate(order.estimated_completion)}; no revised date`,
        tone: "bad",
      };
    }
    const ahead = order.days_ahead;
    if (ahead === null) return { value: shortDate(order.estimated_completion), hint: "", tone: "neutral" };
    if (ahead < 0) return { value: shortDate(order.estimated_completion), hint: `${-ahead} days after promise`, tone: "bad" };
    if (ahead === 0) return { value: shortDate(order.estimated_completion), hint: "no buffer", tone: "warn" };
    return { value: shortDate(order.estimated_completion), hint: `${ahead} days to spare`, tone: "ok" };
  }
  if (order.completion_unknown_reason === null) {
    return { value: "Nothing left to make", hint: "produced or shipped in full", tone: "neutral" };
  }
  if (order.completion_unknown_reason === "materials_not_covered") {
    return { value: "No date yet", hint: "materials not covered", tone: "bad" };
  }
  return { value: "No date yet", hint: "nothing planned for the balance", tone: "warn" };
}

export const FORECAST_TONE: Record<string, string> = {
  ok: "text-ink-500",
  warn: "text-high-text",
  bad: "text-critical-text",
  neutral: "text-ink-500",
};

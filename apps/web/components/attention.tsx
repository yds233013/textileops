"use client";

import Link from "@/components/link";
import { money, num, relativeAge } from "@/lib/format";
import { exceptionTypeLabel } from "@/lib/labels";
import type { AttentionCard as Card, ImpactMetric } from "@/lib/types";
import { IconArrowRight, IconCheckCircle } from "./icons";
import { SEVERITY_EDGE, SeverityBadge } from "./ui";

function MetricChip({ metric }: { metric: ImpactMetric }) {
  if (metric.basis === "unavailable") {
    return (
      <span title={metric.note ?? undefined} className="whitespace-nowrap text-xs text-ink-400">
        {metric.label}: <span className="italic">not available</span>
      </span>
    );
  }
  const value = typeof metric.value === "number" ? String(metric.value) : num(metric.value);
  return (
    <span title={metric.note ?? undefined} className="whitespace-nowrap text-xs text-ink-500">
      {metric.label}{" "}
      <span className="font-semibold text-ink-900 tnum">
        {value}
        {metric.unit ? ` ${metric.unit}` : ""}
      </span>
    </span>
  );
}

const LINK_LABEL: Record<string, string> = {
  order: "Order",
  purchase_order: "Purchase order",
  batch: "Batch",
  material: "Material coverage",
  shipment: "Shipment",
};

function hrefFor(kind: string, id: string): string {
  switch (kind) {
    case "order":
      return `/orders/${id}`;
    case "purchase_order":
      return `/purchase-orders/${id}`;
    case "batch":
      return `/production/${id}`;
    case "material":
      return `/inventory/${id}`;
    default:
      return "/shipments";
  }
}

/**
 * One item in the attention queue: what happened, why it matters, what it
 * costs, and what to do next — in that order, because that is the order the
 * questions arrive in. Compact on purpose: the queue is ranked, and a ranking
 * is only useful if the eye can run down it.
 */
export function AttentionCard({ card }: { card: Card }) {
  const calculated = card.impact_metrics.filter((m) => m.basis !== "unavailable").slice(0, 3);
  const unavailable = card.impact_metrics.filter((m) => m.basis === "unavailable").slice(0, 1);
  const links = Object.entries(card.links).filter(([, id]) => Boolean(id)) as [string, string][];

  return (
    <article className="relative flex gap-4 px-4 py-3.5 pl-5 transition-colors hover:bg-ink-25">
      <span aria-hidden className={`absolute inset-y-3 left-0 w-[3px] rounded-r ${SEVERITY_EDGE[card.severity] ?? "bg-ink-300"}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <SeverityBadge severity={card.severity} />
          <span className="text-xs font-medium text-ink-600">{exceptionTypeLabel(card.exception_type)}</span>
          <span className="text-xs text-ink-400">·</span>
          <span className="text-xs text-ink-400">{relativeAge(card.age_hours)}</span>
          {card.pending_proposal_count > 0 && (
            <span className="ml-auto inline-flex items-center gap-1 rounded-md bg-brand-50 px-1.5 py-[1px] text-xs font-medium text-brand-800 ring-1 ring-inset ring-brand-200">
              <IconCheckCircle size={12} />
              {card.pending_proposal_count} awaiting approval
            </span>
          )}
        </div>

        <h3 className="mt-1.5 text-[14px] font-semibold leading-5 text-ink-950">
          <Link href={`/exceptions/${card.exception_id}`} className="hover:text-brand-700">
            {card.what}
          </Link>
        </h3>
        <p className="mt-0.5 text-[13px] leading-5 text-ink-600">{card.why}</p>

        <div className="mt-2 rounded-md bg-ink-50 px-3 py-2">
          <p className="text-[12.5px] leading-[18px] text-ink-700">
            <span className="font-medium text-ink-500">If nothing changes: </span>
            {card.impact_headline}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
            {calculated.map((metric) => (
              <MetricChip key={metric.key} metric={metric} />
            ))}
            <RevenueChip card={card} />
            {unavailable.map((metric) => (
              <MetricChip key={metric.key} metric={metric} />
            ))}
          </div>
          {card.customers_affected.length > 0 && (
            <p className="mt-1 truncate text-xs text-ink-500">
              Customers: <span className="text-ink-700">{card.customers_affected.join(", ")}</span>
            </p>
          )}
        </div>

        {card.recommended_action && (
          <p className="mt-2 flex gap-1.5 text-[13px] leading-5 text-ink-800">
            <span className="shrink-0 font-semibold text-brand-700">Next step</span>
            <span>{card.recommended_action}</span>
          </p>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <Link
            href={`/exceptions/${card.exception_id}`}
            className="inline-flex items-center gap-1 font-medium text-brand-700 hover:text-brand-900"
          >
            Open investigation <IconArrowRight size={12} />
          </Link>
          {links.map(([kind, id]) => (
            <Link key={kind} href={hrefFor(kind, id)} className="text-ink-500 hover:text-ink-900 hover:underline">
              {LINK_LABEL[kind] ?? kind}
            </Link>
          ))}
          <span className="ml-auto font-mono text-2xs text-ink-400">{card.code}</span>
        </div>
      </div>
    </article>
  );
}

function RevenueChip({ card }: { card: Card }) {
  if (card.revenue_exposure === null || card.revenue_basis === "unavailable") {
    return (
      <span title={card.revenue_note ?? undefined} className="whitespace-nowrap text-xs text-ink-400">
        Revenue exposure: <span className="italic">not available</span>
      </span>
    );
  }
  return (
    <span title={card.revenue_note ?? undefined} className="whitespace-nowrap text-xs text-ink-500">
      Revenue exposure{" "}
      <span className="font-semibold text-ink-900 tnum">{money(card.revenue_exposure, card.currency)}</span>
      {card.revenue_basis === "partial" && <span className="text-ink-400"> (partial)</span>}
    </span>
  );
}

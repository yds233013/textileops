"use client";

import Link from "next/link";
import { humanise, money, relativeAge } from "@/lib/format";
import type { AttentionCard as Card, ImpactMetric } from "@/lib/types";
import { Badge, SeverityBadge } from "./ui";

function MetricChip({ metric }: { metric: ImpactMetric }) {
  if (metric.basis === "unavailable") {
    return (
      <span
        title={metric.note ?? undefined}
        className="inline-flex items-baseline gap-1 rounded bg-ink-50 px-1.5 py-0.5 text-xs text-ink-500"
      >
        {metric.label}: <span className="italic">not available</span>
      </span>
    );
  }
  return (
    <span
      title={metric.note ?? undefined}
      className="inline-flex items-baseline gap-1 rounded bg-ink-50 px-1.5 py-0.5 text-xs text-ink-700"
    >
      {metric.label}:{" "}
      <span className="font-medium tabular-nums text-ink-900">
        {metric.value}
        {metric.unit ? ` ${metric.unit}` : ""}
      </span>
    </span>
  );
}

/**
 * One item in the attention queue, laid out as the four questions an operator
 * actually has: what happened, why it matters, what it costs, what to do.
 */
export function AttentionCard({ card }: { card: Card }) {
  const accent: Record<string, string> = {
    critical: "border-l-critical-solid",
    high: "border-l-high-solid",
    medium: "border-l-medium-solid",
    low: "border-l-low-solid",
  };

  return (
    <article
      className={`rounded-lg border border-ink-200 border-l-4 bg-white p-4 shadow-sm ${
        accent[card.severity] ?? "border-l-ink-300"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={card.severity} />
        <Badge>{humanise(card.exception_type)}</Badge>
        <span className="font-mono text-xs text-ink-400">{card.code}</span>
        <span className="ml-auto text-xs text-ink-500">{relativeAge(card.age_hours)}</span>
      </div>

      <h3 className="mt-2 text-sm font-semibold text-ink-950">
        <Link href={`/exceptions/${card.exception_id}`} className="hover:underline">
          {card.what}
        </Link>
      </h3>
      <p className="mt-1 text-sm text-ink-600">{card.why}</p>

      <div className="mt-3 rounded-md bg-ink-50 px-3 py-2">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
          If nothing changes
        </p>
        <p className="mt-0.5 text-sm text-ink-800">{card.impact_headline}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {card.impact_metrics.slice(0, 4).map((metric) => (
            <MetricChip key={metric.key} metric={metric} />
          ))}
          {/* Omitting the figure when it cannot be computed makes an exception
              of unknown cost look exactly like one that costs nothing, which
              is the more comfortable of the two readings and the wrong one.
              Say that it is unknown, and why. */}
          {card.revenue_exposure ? (
            <span className="inline-flex items-baseline gap-1 rounded bg-white px-1.5 py-0.5 text-xs text-ink-700 ring-1 ring-ink-200">
              Revenue exposure:{" "}
              <span className="font-medium tabular-nums text-ink-900">
                {money(card.revenue_exposure, card.currency)}
              </span>
              {card.revenue_basis === "partial" && (
                <span className="text-ink-500"> (partial)</span>
              )}
            </span>
          ) : (
            <span
              className="inline-flex items-baseline gap-1 rounded bg-white px-1.5 py-0.5 text-xs text-ink-500 ring-1 ring-ink-200"
              title={card.revenue_note ?? undefined}
            >
              Revenue exposure: <span className="font-medium">not available</span>
            </span>
          )}
        </div>
        {card.customers_affected.length > 0 && (
          <p className="mt-2 text-xs text-ink-600">
            Customers affected: {card.customers_affected.join(", ")}
          </p>
        )}
      </div>

      {card.recommended_action && (
        <div className="mt-3">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
            Recommended next step
          </p>
          <p className="mt-0.5 text-sm text-ink-800">{card.recommended_action}</p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-ink-100 pt-3 text-xs">
        <Link
          href={`/exceptions/${card.exception_id}`}
          className="font-medium text-ink-900 hover:underline"
        >
          Open investigation →
        </Link>
        {card.links.order && (
          <Link href={`/orders/${card.links.order}`} className="text-ink-600 hover:underline">
            Order
          </Link>
        )}
        {card.links.purchase_order && (
          <Link
            href={`/purchase-orders/${card.links.purchase_order}`}
            className="text-ink-600 hover:underline"
          >
            Purchase order
          </Link>
        )}
        {card.links.batch && (
          <Link
            href={`/production/${card.links.batch}`}
            className="text-ink-600 hover:underline"
          >
            Batch
          </Link>
        )}
        {card.links.material && (
          <Link
            href={`/inventory/${card.links.material}`}
            className="text-ink-600 hover:underline"
          >
            Material coverage
          </Link>
        )}
        {card.pending_proposal_count > 0 && (
          <Badge tone="warn">
            {card.pending_proposal_count} awaiting approval
          </Badge>
        )}
        {card.has_investigation && <Badge tone="neutral">Investigated</Badge>}
      </div>
    </article>
  );
}

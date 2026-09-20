"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  RiskBadge,
  Select,
  StatusPill,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { date, dueText, money } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { OrderList } from "@/lib/types";

const RISKS = [
  { value: "", label: "All risk levels" },
  { value: "late", label: "Late" },
  { value: "at_risk", label: "At risk" },
  { value: "watch", label: "Watch" },
  { value: "on_track", label: "On track" },
];

export default function OrdersPage() {
  const [risk, setRisk] = useState("");
  const [search, setSearch] = useState("");
  const [includeClosed, setIncludeClosed] = useState(false);
  const { data, error, loading, reload } = useApi<OrderList>("/orders", {
    risk,
    search,
    include_closed: includeClosed,
  });

  return (
    <>
      <PageHeader
        title="Customer orders"
        description="What we promised, what stands between us and delivering it."
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="order-search" className="sr-only">
              Search by order number
            </label>
            <input
              id="order-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Order number…"
              className={inputClass}
            />
          </div>
          <Select id="order-risk" label="Risk" value={risk} onChange={setRisk} options={RISKS} />
          <label className="flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={includeClosed}
              onChange={(event) => setIncludeClosed(event.target.checked)}
              className="rounded border-ink-300"
            />
            Include closed and delivered
          </label>
        </div>
        {data && (
          <p className="mt-3 text-xs text-ink-500">
            {data.total} order(s) · {data.counts_by_risk.late ?? 0} late ·{" "}
            {data.counts_by_risk.at_risk ?? 0} at risk · {data.counts_by_risk.watch ?? 0} on
            watch · {data.counts_by_risk.on_track ?? 0} on track
          </p>
        )}
      </Card>

      <Card title="Orders">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="No orders match"
            description="Try widening the filters, or include closed orders."
          />
        ) : (
          <Table
            caption="Customer orders"
            head={[
              "Order",
              "Customer",
              "Promised",
              "Est. completion",
              "Risk",
              "Material",
              "Production",
              "QC",
              "Shipment",
              "Outstanding value",
              "",
            ]}
          >
            {data.items.map((order) => (
              <tr key={order.id} className="hover:bg-ink-50">
                <Td>
                  <Link
                    href={`/orders/${order.id}`}
                    className="font-medium text-ink-900 hover:underline"
                  >
                    {order.number}
                  </Link>
                </Td>
                <Td>{order.customer_name}</Td>
                <Td className="whitespace-nowrap">
                  {date(order.promised_date)}
                  <span className="block text-xs text-ink-500">
                    {dueText(order.promised_date)}
                  </span>
                </Td>
                <Td className="whitespace-nowrap">
                  {order.estimated_completion ? (
                    <>
                      {date(order.estimated_completion)}
                      <span
                        className={`block text-xs ${
                          (order.days_ahead ?? 0) < 0 ? "text-critical-text" : "text-ink-500"
                        }`}
                      >
                        {order.days_ahead === null
                          ? ""
                          : order.days_ahead >= 0
                            ? `${order.days_ahead} days of buffer`
                            : `${Math.abs(order.days_ahead)} days late`}
                      </span>
                    </>
                  ) : (
                    <span className="text-ink-500">No achievable date</span>
                  )}
                </Td>
                <Td>
                  <RiskBadge risk={order.risk} />
                </Td>
                <Td>
                  <StatusPill value={order.material_readiness} />
                </Td>
                <Td>
                  <StatusPill value={order.production_status} />
                </Td>
                <Td>
                  <StatusPill value={order.qc_status} />
                </Td>
                <Td>
                  <StatusPill value={order.shipment_status} />
                </Td>
                <Td numeric>
                  {order.outstanding_value ? (
                    money(order.outstanding_value, order.currency)
                  ) : (
                    <span className="text-ink-500">Not priced</span>
                  )}
                </Td>
                <Td>
                  {order.open_exception_count > 0 && (
                    <Badge tone="bad">{order.open_exception_count}</Badge>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

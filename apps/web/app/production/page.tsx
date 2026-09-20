"use client";

import Link from "next/link";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { date, percent, quantity } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Batch } from "@/lib/types";

export default function ProductionPage() {
  const { data, error, loading, reload } = useApi<Batch[]>("/production/batches");

  return (
    <>
      <PageHeader
        title="Production"
        description="Batches in flight. The estimate is start plus planned duration, and a batch
          never starts before its materials are on site."
      />
      <Card>
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="Nothing is in production" />
        ) : (
          <Table
            caption="Production batches"
            head={[
              "Batch",
              "Fabric",
              "Stage",
              "Status",
              "Planned",
              "Estimated",
              "Late by",
              "Quantity",
              "Yield",
              "Order",
            ]}
          >
            {data.map((batch) => (
              <tr key={batch.id} className="hover:bg-ink-50">
                <Td>
                  <Link
                    href={`/production/${batch.id}`}
                    className="font-mono text-xs font-medium text-ink-900 hover:underline"
                  >
                    {batch.code}
                  </Link>
                </Td>
                <Td>{batch.fabric_name}</Td>
                <Td className="text-xs">{batch.stage}</Td>
                <Td>
                  <StatusPill value={batch.status} />
                  {batch.blocked_reason && (
                    <span className="mt-0.5 block max-w-xs text-xs text-critical-text">
                      {batch.blocked_reason}
                    </span>
                  )}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {date(batch.planned_start)} → {date(batch.planned_completion)}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {batch.estimated_completion ? (
                    date(batch.estimated_completion)
                  ) : (
                    <span className="text-critical-text">No achievable date</span>
                  )}
                </Td>
                <Td numeric>
                  {batch.delay_days > 0 ? (
                    <span className="font-medium text-critical-text">{batch.delay_days}d</span>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td numeric>{quantity(batch.planned_quantity, batch.unit)}</Td>
                <Td numeric>{batch.yield_pct ? percent(batch.yield_pct, 1) : "—"}</Td>
                <Td className="text-xs">
                  {batch.sales_order_id ? (
                    <Link
                      href={`/orders/${batch.sales_order_id}`}
                      className="text-ink-700 hover:underline"
                    >
                      {batch.sales_order_number}
                    </Link>
                  ) : (
                    <Badge tone="neutral">Stock</Badge>
                  )}
                  {batch.customer_name && (
                    <span className="block text-ink-500">{batch.customer_name}</span>
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

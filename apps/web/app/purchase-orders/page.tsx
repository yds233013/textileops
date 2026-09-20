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
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { date, dueText, humanise } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { PurchaseOrder } from "@/lib/types";

export default function PurchaseOrdersPage() {
  const [search, setSearch] = useState("");
  const [lateOnly, setLateOnly] = useState(false);
  const { data, error, loading, reload } = useApi<PurchaseOrder[]>("/purchase-orders", {
    search,
    late_only: lateOnly,
  });

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="What we are owed, when we currently believe it arrives, and who said so."
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="po-search" className="sr-only">
              Search purchase orders
            </label>
            <input
              id="po-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="PO number…"
              className={inputClass}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={lateOnly}
              onChange={(event) => setLateOnly(event.target.checked)}
              className="rounded border-ink-300"
            />
            Only show overdue orders
          </label>
        </div>
      </Card>

      <Card title="Purchase orders">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="No purchase orders match" />
        ) : (
          <Table
            caption="Purchase orders"
            head={["Number", "Supplier", "Ordered", "Expected", "Status", "Late by", "Notes"]}
          >
            {data.map((po) => (
              <tr key={po.id} className="hover:bg-ink-50">
                <Td>
                  <Link
                    href={`/purchase-orders/${po.id}`}
                    className="font-medium text-ink-900 hover:underline"
                  >
                    {po.number}
                  </Link>
                </Td>
                <Td>{po.supplier_name}</Td>
                <Td>{date(po.order_date)}</Td>
                <Td className="whitespace-nowrap">
                  {date(po.current_expected_date)}
                  <span className="block text-xs text-ink-500">
                    {dueText(po.current_expected_date)}
                  </span>
                  {po.revised_expected_date && (
                    <span className="block text-xs text-high-text">
                      revised from {date(po.expected_date)}
                    </span>
                  )}
                </Td>
                <Td>
                  <Badge tone={po.days_late > 0 ? "bad" : "neutral"}>{humanise(po.status)}</Badge>
                </Td>
                <Td numeric>
                  {po.days_late > 0 ? (
                    <span className="font-medium text-critical-text">{po.days_late} days</span>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td className="text-xs text-ink-600">
                  {po.is_partially_received && <Badge tone="warn">Part received</Badge>}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

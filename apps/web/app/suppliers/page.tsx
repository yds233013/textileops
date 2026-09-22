"use client";

import Link from "@/components/link";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Table,
  RowLink,
  Td,
} from "@/components/ui";
import { percent } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Supplier } from "@/lib/types";

export default function SuppliersPage() {
  const { data, error, loading, reload } = useApi<Supplier[]>("/suppliers");

  return (
    <>
      <PageHeader
        title="Suppliers"
        description="Who we buy from, and how reliably they actually deliver."
      />
      <Card>
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="No suppliers recorded" />
        ) : (
          <Table
            caption="Suppliers"
            head={["Supplier", "Contact", "Lead time", "On-time rate", "Open POs", "Late POs", "Flags"]}
          >
            {data.map((supplier) => (
              <RowLink key={supplier.id} href={`/suppliers/${supplier.id}`}>
                <Td>
                  <Link
                    href={`/suppliers/${supplier.id}`}
                    className="font-medium text-ink-950 group-hover:text-brand-700"
                  >
                    {supplier.name}
                  </Link>
                  <span className="block font-mono text-xs text-ink-500">{supplier.code}</span>
                </Td>
                <Td className="text-xs text-ink-600">
                  {supplier.contact_name ?? "—"}
                  {supplier.contact_email && (
                    <span className="block text-ink-500">{supplier.contact_email}</span>
                  )}
                </Td>
                <Td numeric>{supplier.default_lead_time_days} days</Td>
                <Td numeric>
                  {supplier.on_time_rate ? (
                    percent(supplier.on_time_rate)
                  ) : (
                    <span
                      className="text-ink-500"
                      title="No receipts recorded yet — an unmeasured supplier is not a perfect one."
                    >
                      Not measured
                    </span>
                  )}
                </Td>
                <Td numeric>{supplier.open_po_count}</Td>
                <Td numeric>
                  {supplier.late_po_count > 0 ? (
                    <span className="font-medium text-critical-text">
                      {supplier.late_po_count}
                    </span>
                  ) : (
                    0
                  )}
                </Td>
                <Td>
                  {supplier.open_exception_count > 0 && (
                    <Badge tone="bad">{supplier.open_exception_count} open</Badge>
                  )}
                </Td>
              </RowLink>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

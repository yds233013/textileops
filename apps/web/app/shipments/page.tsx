"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { date, quantity } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Shipment } from "@/lib/types";

export default function ShipmentsPage() {
  const { data, error, loading, reload } = useApi<Shipment[]>("/shipments");
  const [busy, setBusy] = useState<string | null>(null);

  const dispatch = useAction(async (id: string) => {
    setBusy(id);
    await apiFetch(`/shipments/${id}/dispatch`, { body: {} });
    setBusy(null);
    reload();
  });

  const deliver = useAction(async (id: string) => {
    setBusy(id);
    await apiFetch(`/shipments/${id}/delivered`, { body: {} });
    setBusy(null);
    reload();
  });

  return (
    <>
      <PageHeader
        title="Shipments"
        description="What has left the building, and what has not arrived when it should have."
      />
      {(dispatch.error || deliver.error) && (
        <div className="mb-4">
          <ErrorState error={(dispatch.error ?? deliver.error)!} />
        </div>
      )}
      <Card>
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="No shipments recorded" />
        ) : (
          <Table
            caption="Shipments"
            head={[
              "Shipment",
              "Customer",
              "Status",
              "Dispatched",
              "Expected",
              "Delivered",
              "Late by",
              "Lines",
              "",
            ]}
          >
            {data.map((shipment) => (
              <tr key={shipment.id}>
                <Td>
                  <span className="font-medium text-ink-900">{shipment.number}</span>
                  {shipment.tracking_reference && (
                    <span className="block font-mono text-xs text-ink-500">
                      {shipment.tracking_reference}
                    </span>
                  )}
                </Td>
                <Td>{shipment.customer_name}</Td>
                <Td>
                  <StatusPill value={shipment.status} />
                </Td>
                <Td className="whitespace-nowrap text-xs">{date(shipment.dispatch_date)}</Td>
                <Td className="whitespace-nowrap text-xs">
                  {date(shipment.expected_delivery_date)}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {date(shipment.actual_delivery_date)}
                </Td>
                <Td numeric>
                  {shipment.days_late > 0 ? (
                    <Badge tone="bad">
                      {shipment.days_late} days
                      {shipment.delivered_late ? " late" : " overdue"}
                    </Badge>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td className="text-xs text-ink-600">
                  {shipment.lines.map((line) => (
                    <span key={line.id} className="block">
                      {line.sales_order_number}: {quantity(line.quantity, line.unit)}
                    </span>
                  ))}
                  {/* This column shows the *packed* quantity. When dispatch
                      cannot find that much finished cloth it credits only
                      what actually left and writes the difference into the
                      shipment's notes — which were rendered on no page at
                      all, so a dispatch that sent 600 of a packed 1,000 m
                      read here as 1,000 m gone. */}
                  {shipment.notes && shipment.notes.toLowerCase().includes("short") && (
                    <span className="mt-0.5 block text-critical-text">
                      {shipment.notes}
                    </span>
                  )}
                </Td>
                <Td>
                  {["planned", "packed"].includes(shipment.status) && (
                    <Button
                      onClick={() => dispatch.run(shipment.id)}
                      disabled={busy === shipment.id}
                    >
                      Dispatch
                    </Button>
                  )}
                  {["dispatched", "in_transit", "delayed"].includes(shipment.status) && (
                    <Button
                      onClick={() => deliver.run(shipment.id)}
                      disabled={busy === shipment.id}
                    >
                      Mark delivered
                    </Button>
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

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
} from "@/components/ui";
import { date, quantity } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Lot, Position } from "@/lib/types";

export default function InventoryPage() {
  const [shortagesOnly, setShortagesOnly] = useState(false);
  const positions = useApi<Position[]>("/inventory/positions", {
    shortages_only: shortagesOnly,
  });
  const lots = useApi<Lot[]>("/inventory/lots", { limit: 50 });

  return (
    <>
      <PageHeader
        title="Inventory"
        description="On hand, reserved, incoming and required — every figure calculated in code, never
          by a model."
      />

      <Card
        title="Material positions"
        subtitle="Free to promise is what is left after every existing reservation; where
          reservations already exceed the stock on the floor, the over-commitment is shown
          instead of a negative quantity. Projected is what remains once every open batch has
          taken its share."
        actions={
          <label className="flex items-center gap-2 text-xs text-ink-700">
            <input
              type="checkbox"
              checked={shortagesOnly}
              onChange={(event) => setShortagesOnly(event.target.checked)}
              className="rounded border-ink-300"
            />
            Shortages only
          </label>
        }
        className="mb-4"
      >
        {positions.loading && !positions.data ? (
          <Loading />
        ) : positions.error ? (
          <ErrorState error={positions.error} onRetry={positions.reload} />
        ) : !positions.data || positions.data.length === 0 ? (
          <EmptyState
            title={shortagesOnly ? "No material is short" : "No stock recorded"}
            description={
              shortagesOnly
                ? "Every material with demand is covered by stock or confirmed incoming supply."
                : undefined
            }
          />
        ) : (
          <Table
            caption="Material positions"
            head={[
              "Material",
              "On hand",
              "Reserved",
              "Free to promise",
              "Incoming",
              "Required",
              "Projected",
              "Shortage",
              "First short",
            ]}
          >
            {positions.data.map((position) => (
              <tr key={position.material_id} className="hover:bg-ink-50">
                <Td>
                  <Link
                    href={`/inventory/${position.material_id}`}
                    className="font-medium text-ink-900 hover:underline"
                  >
                    {position.material_name}
                  </Link>
                  <span className="block font-mono text-xs text-ink-500">
                    {position.material_code}
                  </span>
                </Td>
                <Td numeric>{quantity(position.on_hand, position.unit)}</Td>
                <Td numeric>{quantity(position.reserved, position.unit)}</Td>
                <Td
                  numeric
                  className={Number(position.available) < 0 ? "text-critical-text" : ""}
                  title={
                    Number(position.over_committed_by) > 0
                      ? `Reservations exceed the stock on the floor by ${quantity(
                          position.over_committed_by,
                          position.unit,
                        )}.`
                      : undefined
                  }
                >
                  {Number(position.available) < 0
                    ? `0 ${position.unit} (over-committed by ${quantity(
                        position.over_committed_by,
                        position.unit,
                      )})`
                    : quantity(position.available, position.unit)}
                </Td>
                <Td numeric>{quantity(position.incoming, position.unit)}</Td>
                <Td numeric>{quantity(position.required, position.unit)}</Td>
                <Td numeric className={Number(position.projected) < 0 ? "text-critical-text" : ""}>
                  {quantity(position.projected, position.unit)}
                </Td>
                <Td numeric>
                  {Number(position.shortage) > 0 ? (
                    <Badge tone="bad">{quantity(position.shortage, position.unit)}</Badge>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {position.first_shortfall_date ? date(position.first_shortfall_date) : "—"}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Recent lots">
        {lots.loading && !lots.data ? (
          <Loading />
        ) : !lots.data || lots.data.length === 0 ? (
          <EmptyState title="No lots recorded" />
        ) : (
          <Table
            caption="Inventory lots"
            head={["Lot", "Item", "On hand", "Received", "Status", "Measured", "Received at"]}
          >
            {lots.data.map((lot) => (
              <tr key={lot.id}>
                <Td className="font-mono text-xs">{lot.lot_code}</Td>
                <Td>{lot.material_name ?? lot.fabric_name ?? "—"}</Td>
                <Td numeric>{quantity(lot.quantity_on_hand, lot.unit)}</Td>
                <Td numeric>{quantity(lot.quantity_received, lot.unit)}</Td>
                <Td>
                  <Badge
                    tone={
                      lot.status === "available"
                        ? "ok"
                        : lot.status === "quarantine"
                          ? "warn"
                          : lot.status === "rejected"
                            ? "bad"
                            : "neutral"
                    }
                  >
                    {lot.status}
                  </Badge>
                </Td>
                <Td className="text-xs text-ink-600">
                  {lot.gsm_actual ? `${lot.gsm_actual} GSM` : ""}
                  {lot.width_cm_actual ? ` · ${lot.width_cm_actual} cm` : ""}
                  {lot.shade_code_actual ? ` · ${lot.shade_code_actual}` : ""}
                  {!lot.gsm_actual && !lot.width_cm_actual && !lot.shade_code_actual && "—"}
                </Td>
                <Td className="whitespace-nowrap text-xs">{date(lot.received_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

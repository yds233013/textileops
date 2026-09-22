"use client";

import Link from "@/components/link";
import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  FilterBar,
  Hint,
  Loading,
  PageHeader,
  RowLink,
  Segmented,
  StatusPill,
  Table,
  Tabs,
  Td,
} from "@/components/ui";
import { num, shortDate } from "@/lib/format";
import { useApi, useInitialParam } from "@/lib/hooks";
import { statusLabel } from "@/lib/labels";
import type { Lot, Position } from "@/lib/types";

type PositionFilter = "all" | "attention" | "yarn" | "other";

function Coverage({ p }: { p: Position }) {
  const shortage = Number(p.shortage);
  if (shortage > 0) {
    return (
      <>
        <Badge tone="bad" dot>
          Short {num(p.shortage)} {p.unit}
        </Badge>
        <span className="mt-0.5 block text-xs text-ink-500">from {shortDate(p.first_shortfall_date)}</span>
      </>
    );
  }
  if (p.first_shortfall_date) {
    return (
      <>
        <Badge tone="warn" dot>
          Arrives late
        </Badge>
        <span className="mt-0.5 block text-xs text-ink-500">needed {shortDate(p.first_shortfall_date)}</span>
      </>
    );
  }
  if (p.reorder_point && Number(p.projected) < Number(p.reorder_point)) {
    return (
      <Badge tone="warn" dot title={`Projected stock falls below the reorder point of ${num(p.reorder_point)} ${p.unit}.`}>
        Below reorder point
      </Badge>
    );
  }
  return (
    <Badge tone="ok" dot>
      Covered
    </Badge>
  );
}

export default function InventoryPage() {
  const [filter, setFilter] = useState<PositionFilter>("all");
  const [lotView, setLotView] = useState<"stock" | "used" | "held">("stock");
  const initialShort = useInitialParam("short");
  useEffect(() => {
    if (initialShort) setFilter("attention");
  }, [initialShort]);

  const positions = useApi<Position[]>("/inventory/positions");
  const lots = useApi<Lot[]>("/inventory/lots", { limit: 200 });

  const all = useMemo(() => positions.data ?? [], [positions.data]);
  const needsAttention = (p: Position) => Number(p.shortage) > 0 || Boolean(p.first_shortfall_date);
  const shown = useMemo(() => {
    const list = all.filter((p) =>
      filter === "attention" ? needsAttention(p) : filter === "yarn" ? p.category === "yarn" : filter === "other" ? p.category !== "yarn" : true,
    );
    // Problems first, then by name — the eye should not have to hunt for red.
    return [...list].sort((a, b) => Number(needsAttention(b)) - Number(needsAttention(a)) || a.material_name.localeCompare(b.material_name));
  }, [all, filter]);

  const lotList = lots.data ?? [];
  const lotGroups = {
    stock: lotList.filter((l) => Number(l.quantity_on_hand) > 0 && l.status === "available"),
    held: lotList.filter((l) => ["quarantine", "rejected"].includes(l.status) && Number(l.quantity_on_hand) > 0),
    used: lotList.filter((l) => Number(l.quantity_on_hand) === 0 || l.status === "consumed"),
  };

  return (
    <>
      <PageHeader
        title="Inventory"
        description="Stock on site, what is already promised to batches, what is on its way, and whether it covers what is planned. Every figure is worked out from the stock ledger, never estimated."
      />

      <Card flush title="Material positions" subtitle="Against every open batch, in the order the batches need it.">
        <FilterBar summary={positions.data ? `${shown.length} of ${all.length} materials` : undefined}>
          <Segmented<PositionFilter>
            label="Materials"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All", count: all.length },
              { value: "attention", label: "Short or late", count: all.filter(needsAttention).length },
              { value: "yarn", label: "Yarn", count: all.filter((p) => p.category === "yarn").length },
              { value: "other", label: "Dyes, chemicals, packing", count: all.filter((p) => p.category !== "yarn").length },
            ]}
          />
        </FilterBar>
        {positions.loading && !positions.data ? (
          <Loading rows={6} />
        ) : positions.error ? (
          <div className="p-4">
            <ErrorState error={positions.error} onRetry={positions.reload} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState compact title={filter === "attention" ? "Nothing is short or late" : "No materials here"} />
        ) : (
          <Table
            caption="Material positions"
            head={[
              "Material",
              "On site",
              "Promised to batches",
              <span key="free" className="inline-flex items-center gap-1">
                Free now
                <Hint>What is left on site after every existing reservation. Never shown below zero: if batches have been promised more than is on site, the over-commitment is shown underneath instead.</Hint>
              </span>,
              "On order",
              "Needed by plan",
              <span key="after" className="inline-flex items-center gap-1">
                After plan
                <Hint>On site plus on order, minus everything the open batches need. Negative means the plan cannot be met from stock and orders already placed.</Hint>
              </span>,
              "Coverage",
            ]}
            align={["left", "right", "right", "right", "right", "right", "right", "left"]}
          >
            {shown.map((p) => {
              const over = Number(p.over_committed_by);
              return (
                <RowLink key={p.material_id} href={`/inventory/${p.material_id}`}>
                  <Td className="min-w-[14rem]">
                    <Link href={`/inventory/${p.material_id}`} className="font-medium text-ink-950 group-hover:text-brand-700">
                      {p.material_name}
                    </Link>
                    <span className="block text-xs text-ink-500">
                      {statusLabel(p.category)} <span className="font-mono text-2xs text-ink-400">· {p.material_code}</span>
                    </span>
                  </Td>
                  <Td numeric>
                    {num(p.on_hand)} {p.unit}
                    {Number(p.quarantined) > 0 && <span className="block text-xs text-high-text">{num(p.quarantined)} held</span>}
                  </Td>
                  <Td numeric className="text-ink-600">{num(p.reserved)}</Td>
                  <Td numeric>
                    {over > 0 ? (
                      <>
                        <span className="text-ink-400">0</span>
                        <span className="block text-xs text-critical-text">over-promised by {num(p.over_committed_by)}</span>
                      </>
                    ) : (
                      num(p.available)
                    )}
                  </Td>
                  <Td numeric className="text-ink-600">{num(p.incoming)}</Td>
                  <Td numeric className="text-ink-600">{num(p.required)}</Td>
                  <Td numeric className={Number(p.projected) < 0 ? "font-semibold text-critical-text" : "text-ink-900"}>
                    {num(p.projected)} {p.unit}
                  </Td>
                  <Td nowrap>
                    <Coverage p={p} />
                  </Td>
                </RowLink>
              );
            })}
          </Table>
        )}
      </Card>

      <div className="mt-6">
        <Card flush title="Lots" subtitle="Physical stock, lot by lot. Quarantined cloth is counted but never offered to an order.">
          <div className="px-4 pt-2">
            <Tabs
              label="Lots"
              value={lotView}
              onChange={setLotView}
              tabs={[
                { value: "stock", label: "In stock", count: lotGroups.stock.length },
                { value: "held", label: "Held", count: lotGroups.held.length },
                { value: "used", label: "Used up", count: lotGroups.used.length },
              ]}
            />
          </div>
          {lots.loading && !lots.data ? (
            <Loading rows={6} />
          ) : lotGroups[lotView].length === 0 ? (
            <EmptyState compact title={lotView === "held" ? "Nothing is held in quarantine" : "No lots here"} />
          ) : (
            <Table
              caption="Inventory lots"
              head={["Lot", "Item", "On hand", "Received", "Status", "Measured", "Location", "Received on"]}
              align={["left", "left", "right", "right", "left", "left", "left", "right"]}
            >
              {lotGroups[lotView].map((lot) => (
                <tr key={lot.id} className="hover:bg-ink-25">
                  <Td nowrap className="font-mono text-xs text-ink-700">{lot.lot_code}</Td>
                  <Td className="text-ink-900">{lot.material_name ?? lot.fabric_name}</Td>
                  <Td numeric className="font-medium text-ink-950">
                    {num(lot.quantity_on_hand)} {lot.unit}
                  </Td>
                  <Td numeric className="text-ink-500">{num(lot.quantity_received)}</Td>
                  <Td nowrap>
                    <StatusPill value={lot.status} />
                  </Td>
                  <Td className="text-xs text-ink-600">
                    {lot.gsm_actual || lot.width_cm_actual || lot.shade_code_actual ? (
                      [
                        lot.gsm_actual && `${num(lot.gsm_actual)} GSM`,
                        lot.width_cm_actual && `${num(lot.width_cm_actual)} cm`,
                        lot.shade_code_actual,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    ) : (
                      <span className="text-ink-300">Not measured</span>
                    )}
                  </Td>
                  <Td className="text-xs text-ink-600">{lot.location || "—"}</Td>
                  <Td numeric className="text-xs text-ink-500">{shortDate(lot.received_at)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}

"use client";

import { useMemo, useState } from "react";
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  FilterBar,
  Loading,
  PageHeader,
  Segmented,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { quantity, shortDate } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Shipment } from "@/lib/types";
import { Track } from "@/components/shipments";

type Filter = "" | "moving" | "overdue" | "planned" | "delivered";

export default function ShipmentsPage() {
  const { data, error, loading, reload } = useApi<Shipment[]>("/shipments");
  const [filter, setFilter] = useState<Filter>("");
  const [confirm, setConfirm] = useState<{ kind: "dispatch" | "deliver"; shipment: Shipment } | null>(null);
  const [tracking, setTracking] = useState("");
  const [deliveredOn, setDeliveredOn] = useState("");

  const act = useAction(async () => {
    if (!confirm) return;
    if (confirm.kind === "dispatch") {
      await apiFetch(`/shipments/${confirm.shipment.id}/dispatch`, {
        body: { tracking_reference: tracking || null },
      });
    } else {
      await apiFetch(`/shipments/${confirm.shipment.id}/delivered`, {
        body: { delivered_on: deliveredOn || null },
      });
    }
    setConfirm(null);
    reload();
  });

  const all = useMemo(() => data ?? [], [data]);
  const groups = useMemo(
    () => ({
      moving: all.filter((s) => ["dispatched", "in_transit", "delayed"].includes(s.status)),
      overdue: all.filter((s) => s.days_late > 0 && s.status !== "delivered"),
      planned: all.filter((s) => ["planned", "packed"].includes(s.status)),
      delivered: all.filter((s) => s.status === "delivered"),
    }),
    [all],
  );
  const shown = filter ? groups[filter] : all;

  return (
    <>
      <PageHeader
        title="Shipments"
        description="What has left the building, and whether it has arrived. A dispatch is not a delivery: on-time performance is measured from confirmed arrival and nothing else."
      />

      <Card flush>
        <FilterBar summary={data ? `${shown.length} ${shown.length === 1 ? "shipment" : "shipments"}` : undefined}>
          <Segmented<Filter>
            label="Shipment state"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "", label: "All", count: all.length },
              { value: "overdue", label: "Overdue", count: groups.overdue.length },
              { value: "moving", label: "On the road", count: groups.moving.length },
              { value: "planned", label: "Not yet dispatched", count: groups.planned.length },
              { value: "delivered", label: "Arrived", count: groups.delivered.length },
            ]}
          />
        </FilterBar>

        {loading && !data ? (
          <Loading rows={4} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState title={all.length === 0 ? "No shipments recorded" : "No shipments in this state"} />
        ) : (
          <Table
            caption="Shipments"
            head={["Shipment", "Customer", "Where it is", "Dispatched", "Expected", "Arrived", "Carrying", ""]}
          >
            {shown.map((shipment) => (
              <tr key={shipment.id} className="hover:bg-ink-25">
                <Td nowrap>
                  <span className="font-semibold text-ink-950">{shipment.number}</span>
                  {shipment.carrier && <span className="block text-xs text-ink-500">{shipment.carrier}</span>}
                  {shipment.tracking_reference && (
                    <span className="block font-mono text-2xs text-ink-400">{shipment.tracking_reference}</span>
                  )}
                </Td>
                <Td className="text-ink-800">{shipment.customer_name}</Td>
                <Td>
                  <Track shipment={shipment} />
                </Td>
                <Td nowrap className="text-ink-700">{shortDate(shipment.dispatch_date)}</Td>
                <Td nowrap className="text-ink-700">{shortDate(shipment.expected_delivery_date)}</Td>
                <Td nowrap className={shipment.actual_delivery_date ? "text-ink-900" : "text-ink-400"}>
                  {shipment.actual_delivery_date ? shortDate(shipment.actual_delivery_date) : "Not confirmed"}
                </Td>
                <Td className="text-xs text-ink-600">
                  {shipment.lines.map((line) => (
                    <span key={line.id} className="block whitespace-nowrap">
                      <span className="font-medium text-ink-800">{line.sales_order_number}</span>{" "}
                      {quantity(line.quantity, line.unit)}
                    </span>
                  ))}
                  {/* Dispatch credits only what actually left; a shortfall is
                      written to the notes and must be visible here, or 600 of
                      a packed 1,000 m reads as 1,000 m gone. */}
                  {shipment.notes && shipment.notes.toLowerCase().includes("short") && (
                    <span className="mt-0.5 block text-critical-text">{shipment.notes}</span>
                  )}
                </Td>
                <Td nowrap className="text-right">
                  {["planned", "packed"].includes(shipment.status) && (
                    <Button size="sm" onClick={() => { setTracking(shipment.tracking_reference ?? ""); setConfirm({ kind: "dispatch", shipment }); }}>
                      Dispatch…
                    </Button>
                  )}
                  {["dispatched", "in_transit", "delayed"].includes(shipment.status) && (
                    <Button size="sm" onClick={() => { setDeliveredOn(""); setConfirm({ kind: "deliver", shipment }); }}>
                      Confirm arrival…
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>


      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.kind === "dispatch" ? `Dispatch ${confirm.shipment.number}` : `Confirm ${confirm?.shipment.number ?? ""} arrived`}
        confirmLabel={confirm?.kind === "dispatch" ? "Dispatch" : "Confirm arrival"}
        pending={act.pending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => act.run()}
        body={
          confirm?.kind === "dispatch" ? (
            <div className="space-y-3">
              <p>
                This takes the finished cloth for {confirm.shipment.customer_name} out of stock and credits it to their
                order as shipped. If less is on the shelf than was packed, only what actually leaves is credited.
              </p>
              <Field label="Tracking or LR number (optional)" htmlFor="tracking">
                <input id="tracking" value={tracking} onChange={(e) => setTracking(e.target.value)} className={inputClass} />
              </Field>
              {act.error && <p className="text-[13px] text-critical-text">{act.error.message}</p>}
            </div>
          ) : confirm ? (
            <div className="space-y-3">
              <p>
                Record that the goods reached {confirm.shipment.customer_name}. On-time delivery is measured from this
                date, so use the day they actually arrived, not the day they were sent.
              </p>
              <Field label="Arrived on (leave blank for today)" htmlFor="delivered-on">
                <input id="delivered-on" type="date" value={deliveredOn} onChange={(e) => setDeliveredOn(e.target.value)} className={inputClass} />
              </Field>
              {act.error && <p className="text-[13px] text-critical-text">{act.error.message}</p>}
            </div>
          ) : null
        }
      />
    </>
  );
}

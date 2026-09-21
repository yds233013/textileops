"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { IconSearch } from "@/components/icons";
import {
  Card,
  EmptyState,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  RowLink,
  Segmented,
  StatusPill,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { dueText, num, shortDate } from "@/lib/format";
import { useApi, useInitialParam } from "@/lib/hooks";
import type { PurchaseOrder } from "@/lib/types";

type Filter = "open" | "overdue" | "closed" | "all";

const CLOSED = new Set(["received", "closed", "cancelled"]);

/** Received against ordered, as a bar and in words. Never implies more arrived than did. */
function Received({ ordered, received, unit }: { ordered: string; received: string; unit: string }) {
  const o = Number(ordered);
  const r = Number(received);
  const pct = o > 0 ? Math.min(100, (r / o) * 100) : 0;
  return (
    <div className="w-40">
      <div className="h-1.5 rounded-full bg-ink-100">
        <div className={`h-1.5 rounded-full ${pct >= 100 ? "bg-good-solid" : pct > 0 ? "bg-medium-solid" : "bg-ink-100"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-ink-600 tnum">
        {num(received)} of {num(ordered)} {unit}
      </p>
    </div>
  );
}

export default function PurchaseOrdersPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const [search, setSearch] = useState("");
  const initial = useInitialParam("overdue");
  useEffect(() => {
    if (initial) setFilter("overdue");
  }, [initial]);
  const { data, error, loading, reload } = useApi<PurchaseOrder[]>("/purchase-orders", { search });

  const all = useMemo(() => data ?? [], [data]);
  const groups = useMemo(
    () => ({
      open: all.filter((po) => !CLOSED.has(po.status)),
      overdue: all.filter((po) => po.days_late > 0),
      closed: all.filter((po) => CLOSED.has(po.status)),
      all,
    }),
    [all],
  );
  const shown = groups[filter];

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="What suppliers owe us, what has actually arrived, and when we now expect the rest — with the message that moved the date, if one did."
      />
      <Card flush>
        <FilterBar summary={data ? `${shown.length} ${shown.length === 1 ? "purchase order" : "purchase orders"}` : undefined}>
          <Segmented<Filter>
            label="Purchase order state"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "open", label: "Open", count: groups.open.length },
              { value: "overdue", label: "Overdue", count: groups.overdue.length },
              { value: "closed", label: "Received and closed", count: groups.closed.length },
              { value: "all", label: "All", count: all.length },
            ]}
          />
          <div className="relative w-56">
            <label htmlFor="po-search" className="sr-only">
              Search by PO number
            </label>
            <IconSearch size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input id="po-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="PO number" className={`${inputClass} pl-8`} />
          </div>
        </FilterBar>

        {loading && !data ? (
          <Loading rows={6} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState title={filter === "overdue" ? "Nothing is overdue" : "No purchase orders here"} />
        ) : (
          <Table caption="Purchase orders" head={["Purchase order", "Material", "Received", "Expected", "Status", "Late by"]} align={["left", "left", "left", "left", "left", "right"]}>
            {shown.map((po) => (
              <RowLink key={po.id} href={`/purchase-orders/${po.id}`}>
                <Td nowrap>
                  <Link href={`/purchase-orders/${po.id}`} className="font-semibold text-ink-950 group-hover:text-brand-700">
                    {po.number}
                  </Link>
                  <span className="block text-xs text-ink-500">{po.supplier_name}</span>
                </Td>
                <Td className="text-ink-800">
                  {(po.items ?? []).map((item, index) => (
                    <span key={index} className="block">
                      {item.material_name}
                    </span>
                  ))}
                </Td>
                <Td>
                  {(po.items ?? []).map((item, index) => (
                    <Received key={index} ordered={item.ordered_quantity} received={item.received_quantity} unit={item.unit} />
                  ))}
                </Td>
                <Td nowrap>
                  <span className={po.days_late > 0 ? "font-medium text-critical-text" : "text-ink-900"}>{shortDate(po.current_expected_date)}</span>
                  {po.revised_expected_date ? (
                    <span className="block text-xs text-high-text">moved from {shortDate(po.expected_date)}</span>
                  ) : (
                    !CLOSED.has(po.status) && <span className="block text-xs text-ink-500">{dueText(po.current_expected_date)}</span>
                  )}
                </Td>
                <Td nowrap>
                  <StatusPill value={po.status} />
                </Td>
                <Td numeric>
                  {po.days_late > 0 ? (
                    <span className="font-semibold text-critical-text">{po.days_late} days</span>
                  ) : (
                    <span className="text-ink-300">—</span>
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

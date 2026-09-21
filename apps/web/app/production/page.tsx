"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { IconSpool } from "@/components/icons";
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
} from "@/components/ui";
import { num, percent, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { statusLabel } from "@/lib/labels";
import type { Batch } from "@/lib/types";

type Filter = "" | "running" | "planned" | "behind" | "blocked";

export default function ProductionPage() {
  const [filter, setFilter] = useState<Filter>("");
  const { data, error, loading, reload } = useApi<Batch[]>("/production/batches");
  const all = useMemo(() => data ?? [], [data]);
  const groups = useMemo(
    () => ({
      running: all.filter((b) => b.status === "in_progress"),
      planned: all.filter((b) => ["planned", "scheduled"].includes(b.status)),
      behind: all.filter((b) => b.delay_days > 0 || !b.estimated_completion),
      blocked: all.filter((b) => b.status === "blocked"),
    }),
    [all],
  );
  const shown = filter ? groups[filter] : all;

  return (
    <>
      <PageHeader
        title="Production"
        description="Every batch on the floor and in the plan. A batch's estimate is its start plus its planned duration, and it never starts before its materials are on site — so a missing material shows up here as a date, or as no date at all."
      />
      <Card flush>
        <FilterBar summary={data ? `${shown.length} ${shown.length === 1 ? "batch" : "batches"}` : undefined}>
          <Segmented<Filter>
            label="Batches"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "", label: "All", count: all.length },
              { value: "running", label: "Running", count: groups.running.length },
              { value: "planned", label: "Planned", count: groups.planned.length },
              { value: "behind", label: "Behind or undated", count: groups.behind.length },
              { value: "blocked", label: "Blocked", count: groups.blocked.length },
            ]}
          />
        </FilterBar>
        {loading && !data ? (
          <Loading rows={8} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState icon={<IconSpool />} title={all.length === 0 ? "Nothing is in production" : "No batches in this state"} />
        ) : (
          <Table
            caption="Production batches"
            head={["Batch", "Fabric", "Status", "Plan", "Forecast finish", "Made", "For"]}
            align={["left", "left", "left", "left", "left", "left", "left"]}
          >
            {shown.map((batch) => {
              const made = Number(batch.output_quantity);
              const planned = Number(batch.planned_quantity) || 1;
              return (
                <RowLink key={batch.id} href={`/production/${batch.id}`}>
                  <Td nowrap>
                    <Link href={`/production/${batch.id}`} className="font-semibold text-ink-950 group-hover:text-brand-700">
                      {batch.code}
                    </Link>
                    <span className="block text-xs text-ink-500">{statusLabel(batch.stage)}</span>
                  </Td>
                  <Td className="max-w-[15rem]">
                    <span className="text-ink-900">{batch.fabric_name}</span>
                    <span className="block text-xs text-ink-500 tnum">
                      {num(batch.planned_quantity)} {batch.unit}
                    </span>
                  </Td>
                  <Td nowrap>
                    <StatusPill value={batch.status} />
                    {batch.blocked_reason && (
                      <span className="mt-0.5 block max-w-xs whitespace-normal text-xs text-critical-text">{batch.blocked_reason}</span>
                    )}
                  </Td>
                  <Td nowrap className="text-ink-700">
                    {shortDate(batch.planned_start)} → {shortDate(batch.planned_completion)}
                  </Td>
                  <Td nowrap>
                    {batch.estimated_completion ? (
                      <>
                        <span className={batch.delay_days > 0 ? "font-medium text-critical-text" : "text-ink-900"}>
                          {shortDate(batch.estimated_completion)}
                        </span>
                        <span className={`block text-xs ${batch.delay_days > 0 ? "text-critical-text" : "text-ink-500"}`}>
                          {batch.delay_days > 0 ? `${batch.delay_days} days behind plan` : "on plan"}
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-critical-text">No date</span>
                        <span className="block text-xs text-ink-500">materials not covered</span>
                      </>
                    )}
                  </Td>
                  <Td>
                    <div className="w-28">
                      <div className="h-1.5 rounded-full bg-ink-100">
                        <div className="h-1.5 rounded-full bg-info-solid" style={{ width: `${Math.min(100, (made / planned) * 100)}%` }} />
                      </div>
                      <span className="mt-1 block text-xs text-ink-500 tnum">
                        {made > 0 ? `${num(batch.output_quantity)} ${batch.unit}` : "Nothing yet"}
                        {batch.yield_pct ? ` · ${percent(batch.yield_pct, 1)} yield` : ""}
                      </span>
                    </div>
                  </Td>
                  <Td className="max-w-[12rem]">
                    {batch.sales_order_id ? (
                      <>
                        <Link href={`/orders/${batch.sales_order_id}`} className="font-medium text-ink-800 hover:text-brand-700">
                          {batch.sales_order_number}
                        </Link>
                        <span className="block truncate text-xs text-ink-500">{batch.customer_name}</span>
                      </>
                    ) : (
                      <span className="text-xs text-ink-400">Stock</span>
                    )}
                  </Td>
                </RowLink>
              );
            })}
          </Table>
        )}
      </Card>
    </>
  );
}

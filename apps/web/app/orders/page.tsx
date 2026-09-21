"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { IconSearch } from "@/components/icons";
import { forecast, FORECAST_TONE, OrderPipeline } from "@/components/orders";
import {
  Card,
  EmptyState,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  RiskBadge,
  RowLink,
  Segmented,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { dueText, money, num, shortDate } from "@/lib/format";
import { useApi, useInitialParam } from "@/lib/hooks";
import type { OrderList } from "@/lib/types";

type RiskFilter = "" | "late" | "at_risk" | "watch" | "on_track";

export default function OrdersPage() {
  const [risk, setRisk] = useState<RiskFilter>("");
  const [search, setSearch] = useState("");
  const [includeClosed, setIncludeClosed] = useState(false);
  const initialRisk = useInitialParam("risk");
  useEffect(() => {
    if (initialRisk) setRisk(initialRisk as RiskFilter);
  }, [initialRisk]);

  const all = useApi<OrderList>("/orders", { search, include_closed: includeClosed });
  const { data, error, loading, reload } = useApi<OrderList>("/orders", {
    risk,
    search,
    include_closed: includeClosed,
  });
  const counts = all.data?.counts_by_risk ?? {};

  return (
    <>
      <PageHeader
        title="Customer orders"
        description="What has been promised, whether it will make it, and the first thing in the way."
      />

      <Card flush>
        <FilterBar summary={data ? `${data.total} ${data.total === 1 ? "order" : "orders"}` : undefined}>
          <Segmented<RiskFilter>
            label="Risk"
            value={risk}
            onChange={setRisk}
            options={[
              { value: "", label: "All", count: all.data?.total },
              { value: "late", label: "Late", count: counts.late ?? 0 },
              { value: "at_risk", label: "At risk", count: counts.at_risk ?? 0 },
              { value: "watch", label: "Watch", count: counts.watch ?? 0 },
              { value: "on_track", label: "On track", count: counts.on_track ?? 0 },
            ]}
          />
          <div className="relative w-56">
            <label htmlFor="order-search" className="sr-only">
              Search by order number
            </label>
            <IconSearch size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              id="order-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Order number"
              className={`${inputClass} pl-8`}
            />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-ink-700">
            <input
              type="checkbox"
              checked={includeClosed}
              onChange={(event) => setIncludeClosed(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            Include delivered and closed
          </label>
        </FilterBar>

        {loading && !data ? (
          <Loading rows={8} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState title="No orders match" description="Widen the filters, or include delivered and closed orders." />
        ) : (
          <Table
            caption="Customer orders"
            head={["Order", "Fabric and value outstanding", "Promised → forecast", "Risk", "Pipeline", "First thing in the way"]}
          >
            {data.items.map((order) => {
              const f = forecast(order);
              const first = order.items?.[0];
              const more = (order.items?.length ?? 0) - 1;
              return (
                <RowLink key={order.id} href={`/orders/${order.id}`}>
                  <Td nowrap>
                    <Link href={`/orders/${order.id}`} className="font-semibold text-ink-950 group-hover:text-brand-700">
                      {order.number}
                    </Link>
                    <span className="block max-w-[11rem] truncate text-xs text-ink-500">{order.customer_name}</span>
                  </Td>
                  <Td className="max-w-[13rem]">
                    {first ? (
                      <>
                        <span className="block truncate text-ink-800" title={first.fabric_name}>
                          {first.fabric_name}
                        </span>
                        <span className="block text-xs text-ink-500 tnum">
                          {num(first.outstanding_quantity)} of {num(first.quantity)} {first.unit} to go
                          {more > 0 ? ` · +${more} more ${more === 1 ? "line" : "lines"}` : ""}
                        </span>
                        <span className="block text-xs text-ink-700 tnum">
                          {order.outstanding_value ? (
                            money(order.outstanding_value, order.currency)
                          ) : (
                            <span className="text-ink-400">Not priced</span>
                          )}
                        </span>
                      </>
                    ) : (
                      <span className="text-ink-400">—</span>
                    )}
                  </Td>
                  <Td className="w-[11.5rem]">
                    <span className="whitespace-nowrap text-ink-900">
                      {shortDate(order.promised_date)}
                      <span className="text-ink-300"> → </span>
                      <span className={f.tone === "bad" ? "font-medium text-critical-text" : "text-ink-900"}>{f.value}</span>
                    </span>
                    <span className={`block text-xs ${f.hint ? FORECAST_TONE[f.tone] : "text-ink-500"}`}>
                      {f.hint || dueText(order.promised_date)}
                    </span>
                  </Td>
                  <Td nowrap>
                    <RiskBadge risk={order.risk} />
                  </Td>
                  <Td>
                    <OrderPipeline order={order} />
                  </Td>
                  <Td className="w-[14rem] text-[13px]">
                    {order.next_blocker ? (
                      <span className="text-ink-800">{order.next_blocker}</span>
                    ) : (
                      <span className="text-ink-400">
                        {order.risk === "on_track" ? "Date holds" : "Nothing named"}
                      </span>
                    )}
                    {order.open_exception_count > 0 && (
                      <span className="mt-0.5 block text-xs text-critical-text">
                        {order.open_exception_count} open {order.open_exception_count === 1 ? "exception" : "exceptions"}
                      </span>
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

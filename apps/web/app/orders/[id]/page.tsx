"use client";

import Link from "@/components/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { IconAlert, IconArrowRight } from "@/components/icons";
import { forecast, FORECAST_TONE } from "@/components/orders";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  READINESS_TONE,
  RiskBadge,
  SeverityBadge,
  Skeleton,
  StatusPill,
  Table,
  Td,
  Timeline,
  type Tone,
} from "@/components/ui";
import { dateTime, daysFromNow, dueText, money, num, shortDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { exceptionTypeLabel, statusLabel } from "@/lib/labels";
import type { BatchDetail, OperationalException, OrderDetail, TimelineEntry } from "@/lib/types";

const RING: Record<Tone, string> = {
  ok: "border-good-solid bg-good-solid",
  warn: "border-medium-solid bg-medium-solid",
  bad: "border-critical-solid bg-critical-solid",
  info: "border-info-solid bg-info-solid",
  neutral: "border-ink-300 bg-white",
};

/** One stage of the order's journey. */
function Stage({
  label,
  status,
  children,
  last = false,
}: {
  label: string;
  status: string;
  children?: ReactNode;
  last?: boolean;
}) {
  const tone = READINESS_TONE[status] ?? "neutral";
  return (
    <li className="relative flex-1 min-w-[10rem]">
      {!last && <span aria-hidden className="absolute left-3 right-0 top-[7px] hidden h-px bg-ink-200 md:block" />}
      <div className="relative flex items-center gap-2">
        <span aria-hidden className={`z-10 h-[15px] w-[15px] shrink-0 rounded-full border-2 ${RING[tone]}`} />
        <span className="text-2xs font-semibold uppercase tracking-wider text-ink-500">{label}</span>
      </div>
      <div className="mt-2 pr-4">
        <StatusPill value={status} />
        {children && <div className="mt-1.5 text-xs leading-4 text-ink-600">{children}</div>}
      </div>
    </li>
  );
}

function BatchCard({ batchId }: { batchId: string }) {
  const { data } = useApi<BatchDetail>(`/production/batches/${batchId}`);
  if (!data) {
    return (
      <div className="rounded-md border border-ink-150 p-3">
        <Skeleton className="w-40" />
        <Skeleton className="mt-2 w-64" />
      </div>
    );
  }
  const materialsLate =
    data.material_ready_date && data.material_ready_date > data.planned_start && data.status !== "completed";
  return (
    <div className="rounded-md border border-ink-150">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-ink-100 px-3 py-2">
        <Link href={`/production/${data.id}`} className="font-semibold text-ink-950 hover:text-brand-700">
          {data.code}
        </Link>
        <StatusPill value={data.status} />
        <span className="text-xs text-ink-500">
          {statusLabel(data.stage)} · {num(data.planned_quantity)} {data.unit}
        </span>
        <span className="ml-auto text-xs text-ink-600 tnum">
          {shortDate(data.planned_start)} → {shortDate(data.estimated_completion ?? data.planned_completion)}
          {data.delay_days > 0 && <span className="ml-1.5 font-semibold text-high-text">{data.delay_days} d late</span>}
        </span>
      </div>
      {data.blocked_reason && (
        <p className="border-b border-ink-100 bg-critical-bg px-3 py-1.5 text-xs text-critical-text">
          Blocked: {data.blocked_reason}
        </p>
      )}
      {data.requirements.length > 0 ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-2xs uppercase tracking-wider text-ink-400">
              <th className="px-3 pb-1 pt-2 font-semibold">Material</th>
              <th className="px-3 pb-1 pt-2 text-right font-semibold">Needed</th>
              <th className="px-3 pb-1 pt-2 text-right font-semibold">Issued</th>
              <th className="px-3 pb-1 pt-2 font-semibold">By</th>
            </tr>
          </thead>
          <tbody>
            {data.requirements.map((req) => (
              <tr key={req.material_id} className="border-t border-ink-50">
                <td className="px-3 py-1.5">
                  <Link href={`/inventory/${req.material_id}`} className="text-ink-800 hover:text-brand-700">
                    {req.material_name}
                  </Link>
                </td>
                <td className="px-3 py-1.5 text-right text-ink-800 tnum">
                  {num(req.required_quantity)} {req.unit}
                </td>
                <td className="px-3 py-1.5 text-right text-ink-500 tnum">{num(req.issued_quantity)}</td>
                <td className="px-3 py-1.5 text-ink-600">{shortDate(req.required_by)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3 py-2 text-xs text-ink-500">No material requirements recorded.</p>
      )}
      <p className={`border-t border-ink-100 px-3 py-1.5 text-xs ${materialsLate ? "text-high-text" : "text-ink-500"}`}>
        {data.material_ready_date
          ? materialsLate
            ? `Not all of its materials are on site until ${shortDate(data.material_ready_date)}, after the planned start (${shortDate(data.planned_start)}).`
            : `Materials on site by ${shortDate(data.material_ready_date)}.`
          : "No date by which every material is covered: at least one is short."}
      </p>
    </div>
  );
}

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<OrderDetail>(`/orders/${id}`);
  const timeline = useApi<TimelineEntry[]>(`/orders/${id}/timeline`);
  const exceptions = useApi<{ items: OperationalException[] }>("/exceptions", { sales_order_id: id });

  if (loading && !data) return <Loading variant="page" label="Opening the order" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const f = forecast(data);
  const batchIds = Array.from(new Set(data.lines.flatMap((line) => line.batch_ids)));
  const promisedIn = daysFromNow(data.promised_date);
  const open = !["delivered", "closed", "cancelled"].includes(data.status);
  const totalBy = (unit: string, pick: (l: OrderDetail["lines"][number]) => string) =>
    data.lines.filter((l) => l.unit === unit).reduce((sum, l) => sum + Number(pick(l)), 0);
  const units = Array.from(new Set(data.lines.map((l) => l.unit)));

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Customer orders", href: "/orders" }]}
        eyebrow={data.customer_name}
        title={data.number}
        meta={
          <>
            <RiskBadge risk={data.risk} />
            <StatusPill value={data.status} />
            {data.customer_reference && <span className="text-xs text-ink-500">Their ref. {data.customer_reference}</span>}
            <span className="text-xs text-ink-500">Ordered {shortDate(data.order_date)}</span>
          </>
        }
      />

      {/* ------------------------------------------------ the answer first */}
      <div className="mb-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="grid grid-cols-3 divide-x divide-ink-100 rounded-lg border border-ink-150 bg-white shadow-card">
          <div className="px-4 py-3.5">
            <p className="text-xs text-ink-500">Promised</p>
            <p className="mt-1 text-lg font-semibold text-ink-950">{shortDate(data.promised_date)}</p>
            <p className={`text-xs ${promisedIn !== null && promisedIn < 0 && open ? "text-critical-text" : "text-ink-500"}`}>
              {dueText(data.promised_date)}
            </p>
          </div>
          <div className="px-4 py-3.5">
            <p className="text-xs text-ink-500">Forecast finish</p>
            <p className={`mt-1 text-lg font-semibold ${f.tone === "bad" ? "text-critical-text" : "text-ink-950"}`}>{f.value}</p>
            <p className={`text-xs ${FORECAST_TONE[f.tone]}`}>{f.hint || " "}</p>
          </div>
          <div className="px-4 py-3.5">
            <p className="text-xs text-ink-500">Outstanding</p>
            <p className="mt-1 text-lg font-semibold text-ink-950 tnum">
              {data.outstanding_value ? money(data.outstanding_value, data.currency) : <span className="text-[15px] text-ink-400">Not priced</span>}
            </p>
            <p className="text-xs text-ink-500">
              {units.map((u) => `${num(totalBy(u, (l) => l.outstanding_quantity))} ${u}`).join(" · ")} to go
            </p>
          </div>
        </div>

        <div
          className={`flex gap-3 rounded-lg border px-4 py-3.5 ${
            data.next_blocker ? "border-high-border bg-high-bg" : "border-good-border bg-good-bg"
          }`}
        >
          <IconAlert className={`mt-0.5 shrink-0 ${data.next_blocker ? "text-high-solid" : "text-good-solid"}`} />
          <div className="min-w-0 text-[13.5px]">
            <p className={`font-semibold ${data.next_blocker ? "text-high-text" : "text-good-text"}`}>
              {data.next_blocker ? "Why this order might be late" : "Nothing is flagged against this order"}
            </p>
            <p className="mt-0.5 text-ink-800">
              {data.next_blocker ??
                "Every check on its materials, production, quality and shipment is within bounds. TextileOps keeps checking."}
            </p>
            {data.blocked_reasons.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-ink-700">
                {data.blocked_reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            )}
            {(exceptions.data?.items.length ?? 0) > 0 && (
              <a href="#exceptions" className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-900">
                {exceptions.data!.items.length} open {exceptions.data!.items.length === 1 ? "exception" : "exceptions"} <IconArrowRight size={12} />
              </a>
            )}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------- journey */}
      <Card title="Journey" subtitle="Order → materials → production → quality → shipment. Each stage is worked out from the records, not typed in." className="mb-6">
        <ol className="flex flex-wrap gap-y-4 py-1">
          <Stage label="Order" status={data.status}>
            {data.lines.length} {data.lines.length === 1 ? "line" : "lines"} ·{" "}
            {units.map((u) => `${num(totalBy(u, (l) => l.quantity))} ${u}`).join(" · ")}
          </Stage>
          <Stage label="Materials" status={data.material_readiness}>
            {data.material_readiness === "short"
              ? "At least one material is short for a planned batch."
              : data.material_readiness === "partial"
                ? "Some material arrives after the batch needs it."
                : data.material_readiness === "ready"
                  ? "Covered for every open batch."
                  : "No batch needs materials."}
          </Stage>
          <Stage label="Production" status={data.production_status}>
            {batchIds.length} {batchIds.length === 1 ? "batch" : "batches"}
          </Stage>
          <Stage label="Quality" status={data.qc_status} />
          <Stage label="Shipment" status={data.shipment_status} last>
            {units.map((u) => `${num(totalBy(u, (l) => l.shipped_quantity))} ${u} shipped`).join(" · ")}
          </Stage>
        </ol>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <Card title="Lines" flush>
            <Table
              caption="Order lines"
              head={["#", "Fabric", "Ordered", "In stock", "Made", "Shipped", "Outstanding", "Ready by", "Value"]}
              align={["left", "left", "right", "right", "right", "right", "right", "left", "right"]}
            >
              {data.lines.map((line) => (
                <tr key={line.id}>
                  <Td className="text-ink-500">{line.line_no}</Td>
                  <Td className="min-w-[12rem]">
                    <span className="text-ink-900">{line.fabric_name}</span>
                    <span className="block font-mono text-2xs text-ink-400">{line.fabric_code}</span>
                  </Td>
                  <Td numeric>{num(line.quantity)} {line.unit}</Td>
                  <Td numeric>{num(line.stock_available)}</Td>
                  <Td numeric>{num(line.produced_quantity)}</Td>
                  <Td numeric>{num(line.shipped_quantity)}</Td>
                  <Td numeric className="font-medium text-ink-950">{num(line.outstanding_quantity)} {line.unit}</Td>
                  <Td nowrap>{line.estimated_ready_date ? shortDate(line.estimated_ready_date) : <span className="text-ink-400">No date</span>}</Td>
                  <Td numeric>{line.outstanding_value ? money(line.outstanding_value, data.currency) : <span className="text-ink-400">—</span>}</Td>
                </tr>
              ))}
            </Table>
          </Card>

          <Card title="Production and materials" subtitle="Every batch making this order, and what it needs." >
            {batchIds.length === 0 ? (
              <EmptyState compact title="No production batches" description="This order is being served from stock, or nothing has been planned yet." />
            ) : (
              <div className="space-y-3">
                {batchIds.map((batchId) => (
                  <BatchCard key={batchId} batchId={batchId} />
                ))}
              </div>
            )}
          </Card>

          <Card title="History" subtitle="Everything that has happened to this order, in order." >
            {timeline.loading && !timeline.data ? (
              <Loading rows={3} />
            ) : !timeline.data || timeline.data.length === 0 ? (
              <EmptyState compact title="No events recorded" />
            ) : (
              <Timeline
                items={[...timeline.data].reverse().map((entry, index) => ({
                  key: `${entry.at}-${index}`,
                  at: dateTime(entry.at),
                  title: entry.title,
                  detail: entry.detail,
                }))}
              />
            )}
          </Card>
        </div>

        <aside className="space-y-6">
          <Card title="Open exceptions" id="exceptions" flush>
            {exceptions.loading && !exceptions.data ? (
              <Loading rows={2} />
            ) : !exceptions.data || exceptions.data.items.length === 0 ? (
              <EmptyState compact title="Nothing flagged against this order" />
            ) : (
              <ul className="divide-y divide-ink-100">
                {exceptions.data.items.map((item) => (
                  <li key={item.id}>
                    <Link href={`/exceptions/${item.id}`} className="block px-4 py-3 hover:bg-ink-25">
                      <div className="flex items-center gap-2">
                        <SeverityBadge severity={item.severity} />
                        <span className="text-xs text-ink-500">{exceptionTypeLabel(item.exception_type)}</span>
                      </div>
                      <p className="mt-1 text-[13px] font-medium leading-5 text-ink-900">{item.title}</p>
                      {item.recommended_action && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-ink-500">Next: {item.recommended_action}</p>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Customer">
            <p className="text-[13.5px] font-medium text-ink-900">{data.customer_name}</p>
            <p className="mt-1 text-xs text-ink-500">Priced in {data.currency}.</p>
            {data.value_basis !== "complete" && data.value_basis !== "calculated" && (
              <p className="mt-2">
                <Badge tone="warn">
                  {data.value_basis === "partial" ? "Some lines have no price" : "No prices recorded"}
                </Badge>
              </p>
            )}
            {data.notes && <p className="mt-2 text-[13px] text-ink-700">{data.notes}</p>}
          </Card>
        </aside>
      </div>
    </>
  );
}

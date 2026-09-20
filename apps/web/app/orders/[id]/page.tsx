"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Badge,
  Card,
  DefinitionList,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  RiskBadge,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { date, dateTime, dueText, humanise, money, quantity } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { OrderDetail, OperationalException, TimelineEntry } from "@/lib/types";

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<OrderDetail>(`/orders/${id}`);
  const timeline = useApi<TimelineEntry[]>(`/orders/${id}/timeline`);
  const exceptions = useApi<{ items: OperationalException[] }>("/exceptions", {
    sales_order_id: id,
  });

  if (loading && !data) return <Loading label="Opening the order" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Customer orders", href: "/orders" }]}
        title={`${data.number} · ${data.customer_name}`}
        description={
          data.customer_reference
            ? `Their reference: ${data.customer_reference}`
            : undefined
        }
        actions={<RiskBadge risk={data.risk} />}
      />

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Card title="Position" className="lg:col-span-2">
          <DefinitionList
            items={[
              { term: "Status", value: <StatusPill value={data.status} /> },
              { term: "Ordered", value: date(data.order_date) },
              {
                term: "Promised",
                value: date(data.promised_date),
                hint: dueText(data.promised_date),
              },
              {
                term: "Estimated completion",
                value: data.estimated_completion ? (
                  date(data.estimated_completion)
                ) : (
                  <span className="text-ink-500">No achievable date</span>
                ),
                hint:
                  data.days_ahead === null
                    ? "Nothing in stock and nothing planned for the outstanding quantity."
                    : data.days_ahead >= 0
                      ? `${data.days_ahead} days of buffer`
                      : `${Math.abs(data.days_ahead)} days beyond the promise`,
              },
              { term: "Material readiness", value: <StatusPill value={data.material_readiness} /> },
              { term: "Production", value: <StatusPill value={data.production_status} /> },
              { term: "Quality", value: <StatusPill value={data.qc_status} /> },
              { term: "Shipment", value: <StatusPill value={data.shipment_status} /> },
              {
                term: "Outstanding value",
                value: data.outstanding_value ? (
                  money(data.outstanding_value, data.currency)
                ) : (
                  <span className="text-ink-500">Not available</span>
                ),
                hint:
                  data.value_basis === "partial"
                    ? "Some lines have no unit price."
                    : data.value_basis === "unavailable"
                      ? "No unit prices are recorded on this order."
                      : undefined,
              },
            ]}
          />
          {data.blocked_reasons.length > 0 && (
            <div className="mt-4 rounded border border-high-border bg-high-bg px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-high-text">
                Blocked
              </p>
              <ul className="mt-1 space-y-0.5 text-sm text-high-text">
                {data.blocked_reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card title="Open exceptions">
          {exceptions.loading && !exceptions.data ? (
            <Loading />
          ) : !exceptions.data || exceptions.data.items.length === 0 ? (
            <EmptyState title="Nothing flagged against this order" />
          ) : (
            <ul className="space-y-2">
              {exceptions.data.items.map((item) => (
                <li key={item.id} className="rounded border border-ink-200 p-2.5">
                  <Link
                    href={`/exceptions/${item.id}`}
                    className="text-sm font-medium text-ink-900 hover:underline"
                  >
                    {item.title}
                  </Link>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge
                      tone={
                        item.severity === "critical" || item.severity === "high" ? "bad" : "warn"
                      }
                    >
                      {item.severity}
                    </Badge>
                    <Badge tone="neutral">{humanise(item.exception_type)}</Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Order lines" className="mb-4">
        <Table
          caption="Lines on this order"
          head={[
            "#",
            "Fabric",
            "Ordered",
            "In stock",
            "To produce",
            "Produced",
            "Shipped",
            "Outstanding",
            "Ready by",
            "Value",
          ]}
        >
          {data.lines.map((line) => (
            <tr key={line.id}>
              <Td>{line.line_no}</Td>
              <Td>
                <span className="font-medium text-ink-900">{line.fabric_name}</span>
                <span className="block font-mono text-xs text-ink-500">{line.fabric_code}</span>
                {line.blocked_batch_codes.length > 0 && (
                  <span className="mt-1 block text-xs text-critical-text">
                    Blocked: {line.blocked_batch_codes.join(", ")}
                  </span>
                )}
              </Td>
              <Td numeric>{quantity(line.quantity, line.unit)}</Td>
              <Td numeric>{quantity(line.stock_available, line.unit)}</Td>
              <Td numeric>{quantity(line.to_produce, line.unit)}</Td>
              <Td numeric>{quantity(line.produced_quantity, line.unit)}</Td>
              <Td numeric>{quantity(line.shipped_quantity, line.unit)}</Td>
              <Td numeric className="font-medium">
                {quantity(line.outstanding_quantity, line.unit)}
              </Td>
              <Td className="whitespace-nowrap">
                {line.estimated_ready_date ? (
                  date(line.estimated_ready_date)
                ) : (
                  <span className="text-ink-500">Unknown</span>
                )}
              </Td>
              <Td numeric>
                {line.outstanding_value ? (
                  money(line.outstanding_value, data.currency)
                ) : (
                  <span className="text-ink-500">—</span>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card title="Timeline" subtitle="Everything that has happened to this order, in order.">
        {timeline.loading && !timeline.data ? (
          <Loading />
        ) : !timeline.data || timeline.data.length === 0 ? (
          <EmptyState title="Nothing recorded yet" />
        ) : (
          <ol className="space-y-3">
            {timeline.data.map((entry, index) => (
              <li key={index} className="flex gap-3">
                <div className="w-36 shrink-0 text-xs text-ink-500">{dateTime(entry.at)}</div>
                <div className="min-w-0 border-l border-ink-200 pl-3">
                  <p className="text-sm font-medium text-ink-900">{entry.title}</p>
                  <p className="text-sm text-ink-600">{entry.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}

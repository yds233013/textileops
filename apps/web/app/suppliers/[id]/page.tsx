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
  Table,
  RowLink,
  Td,
} from "@/components/ui";
import { date, dateTime, humanise, percent } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { SupplierDetail } from "@/lib/types";

export default function SupplierDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<SupplierDetail>(`/suppliers/${params.id}`);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const supplier = data.supplier;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Suppliers", href: "/suppliers" }]}
        title={supplier.name}
        description={`${supplier.code} · ${supplier.country}`}
      />

      <Card title="Details" className="mb-4">
        <DefinitionList
          items={[
            { term: "Contact", value: supplier.contact_name ?? "—" },
            { term: "Email", value: supplier.contact_email ?? "—" },
            { term: "Phone", value: supplier.contact_phone ?? "—" },
            { term: "Currency", value: supplier.currency },
            { term: "Agreed lead time", value: `${supplier.default_lead_time_days} days` },
            {
              term: "On-time rate",
              value: supplier.on_time_rate ? percent(supplier.on_time_rate) : "Not measured",
              hint: supplier.on_time_rate
                ? "Calculated from actual receipt dates against promised dates."
                : "No receipts recorded against this supplier yet.",
            },
          ]}
        />
      </Card>

      <Card title="Purchase orders" className="mb-4">
        {data.purchase_orders.length === 0 ? (
          <EmptyState title="No purchase orders" />
        ) : (
          <Table
            caption="Purchase orders with this supplier"
            head={["Number", "Ordered", "Expected", "Status", "Late by", "Lines"]}
          >
            {data.purchase_orders.map((po) => (
              <RowLink key={po.id} href={`/purchase-orders/${po.id}`}>
                <Td>
                  <Link
                    href={`/purchase-orders/${po.id}`}
                    className="font-medium text-ink-950 group-hover:text-brand-700"
                  >
                    {po.number}
                  </Link>
                </Td>
                <Td>{date(po.order_date)}</Td>
                <Td>
                  {date(po.current_expected_date)}
                  {po.revised_expected_date && (
                    <span className="block text-xs text-high-text">
                      revised from {date(po.expected_date)}
                    </span>
                  )}
                </Td>
                <Td>
                  <Badge tone={po.days_late > 0 ? "bad" : "neutral"}>
                    {humanise(po.status)}
                  </Badge>
                </Td>
                <Td numeric>{po.days_late > 0 ? `${po.days_late} days` : "—"}</Td>
                <Td numeric>{po.total_ordered_lines}</Td>
              </RowLink>
            ))}
          </Table>
        )}
      </Card>

      <Card
        title="Messages received"
        subtitle="Untrusted third-party text, shown as it arrived. TextileOps extracts claims from
          it; it never takes instructions from it."
      >
        {data.recent_messages.length === 0 ? (
          <EmptyState title="No messages from this supplier" />
        ) : (
          <ul className="space-y-3">
            {data.recent_messages.map((message) => (
              <li key={message.id} className="rounded border border-ink-200 p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm font-medium text-ink-900">
                    {message.subject ?? "(no subject)"}
                  </span>
                  <Badge tone="neutral">{humanise(message.intent)}</Badge>
                  {message.is_duplicate && <Badge tone="warn">Duplicate</Badge>}
                  <span className="ml-auto text-xs text-ink-500">
                    {dateTime(message.received_at)}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-ink-500">From {message.sender}</p>
                <pre className="mt-2 whitespace-pre-wrap rounded bg-ink-50 px-2.5 py-2 text-xs text-ink-700">
                  {message.body}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

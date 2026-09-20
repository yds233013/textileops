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
  Td,
} from "@/components/ui";
import { date, quantity } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Coverage } from "@/lib/types";

export default function MaterialCoveragePage() {
  const params = useParams<{ materialId: string }>();
  const { data, error, loading, reload } = useApi<Coverage>(
    `/inventory/coverage/${params.materialId}`,
  );

  if (loading && !data) return <Loading label="Calculating coverage" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const position = data.position;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Inventory", href: "/inventory" }]}
        title={position.material_name}
        description={`${position.material_code} · coverage to ${date(data.horizon)}`}
      />

      <Card title="Position" className="mb-4">
        <DefinitionList
          items={[
            { term: "On hand", value: quantity(position.on_hand, position.unit) },
            { term: "Quarantined", value: quantity(position.quarantined, position.unit) },
            { term: "Reserved", value: quantity(position.reserved, position.unit) },
            {
              term: "Free to promise",
              value:
                Number(position.available) < 0
                  ? `0 ${position.unit}`
                  : quantity(position.available, position.unit),
              hint:
                Number(position.over_committed_by) > 0
                  ? `Reservations exceed stock on the floor by ${quantity(
                      position.over_committed_by,
                      position.unit,
                    )}.`
                  : "After every existing reservation.",
            },
            { term: "Confirmed incoming", value: quantity(position.incoming, position.unit) },
            { term: "Required in horizon", value: quantity(position.required, position.unit) },
            {
              term: "Shortage",
              value:
                Number(position.shortage) > 0 ? (
                  <Badge tone="bad">{quantity(position.shortage, position.unit)}</Badge>
                ) : (
                  "None"
                ),
            },
          ]}
        />
        <p className="mt-3 rounded bg-ink-50 px-3 py-2 text-sm text-ink-700">
          {data.explanation}
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Demand" subtitle="Allocated earliest-required-first.">
          {data.allocations.length === 0 ? (
            <EmptyState title="Nothing needs this material" />
          ) : (
            <Table
              caption="Demand for this material"
              head={["Batch", "Needed by", "Quantity", "Covered", "Short", "Covered by", "Order"]}
            >
              {data.allocations.map((allocation) => (
                <tr
                  key={allocation.production_batch_id}
                  className={allocation.is_short || allocation.is_late ? "bg-critical-bg/40" : ""}
                >
                  <Td>
                    <Link
                      href={`/production/${allocation.production_batch_id}`}
                      className="font-mono text-xs text-ink-900 hover:underline"
                    >
                      {allocation.production_batch_code}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap text-xs">{date(allocation.required_by)}</Td>
                  <Td numeric>{quantity(allocation.quantity, position.unit)}</Td>
                  <Td numeric>{quantity(allocation.covered_quantity, position.unit)}</Td>
                  <Td numeric>
                    {Number(allocation.shortfall_quantity) > 0 ? (
                      <span className="font-medium text-critical-text">
                        {quantity(allocation.shortfall_quantity, position.unit)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </Td>
                  <Td className="whitespace-nowrap text-xs">
                    {allocation.covered_by_date ? (
                      <>
                        {date(allocation.covered_by_date)}
                        {allocation.is_late && (
                          <span className="block text-critical-text">arrives too late</span>
                        )}
                      </>
                    ) : (
                      "from stock"
                    )}
                  </Td>
                  <Td className="text-xs">
                    {allocation.sales_order_id ? (
                      <Link
                        href={`/orders/${allocation.sales_order_id}`}
                        className="text-ink-700 hover:underline"
                      >
                        {allocation.sales_order_number}
                      </Link>
                    ) : (
                      "—"
                    )}
                    {allocation.customer_name && (
                      <span className="block text-ink-500">{allocation.customer_name}</span>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Confirmed incoming supply">
          {data.incoming.length === 0 ? (
            <EmptyState title="Nothing on order" />
          ) : (
            <Table
              caption="Incoming supply"
              head={["Purchase order", "Supplier", "Quantity", "Expected"]}
            >
              {data.incoming.map((line) => (
                <tr key={line.purchase_order_id}>
                  <Td>
                    <Link
                      href={`/purchase-orders/${line.purchase_order_id}`}
                      className="font-medium text-ink-900 hover:underline"
                    >
                      {line.purchase_order_number}
                    </Link>
                  </Td>
                  <Td>{line.supplier_name}</Td>
                  <Td numeric>{quantity(line.quantity, line.unit)}</Td>
                  <Td className="whitespace-nowrap text-xs">
                    {date(line.expected_date)}
                    {line.is_revised && (
                      <span className="block text-high-text">revised by the supplier</span>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}

"use client";

import { useParams } from "next/navigation";
import { Fragment, useState } from "react";
import {
  Badge,
  Button,
  Card,
  DefinitionList,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { date, dateTime, dueText, humanise, money, quantity } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { POLine, PurchaseOrderDetail } from "@/lib/types";

function ReceiveForm({ line, onDone }: { line: POLine; onDone: () => void }) {
  const [amount, setAmount] = useState(line.outstanding_quantity);
  const [reference, setReference] = useState("");
  const receive = useAction(async () => {
    await apiFetch("/purchase-orders/receipts", {
      body: {
        purchase_order_line_id: line.id,
        accepted_quantity: amount,
        unit: line.unit,
        supplier_document_ref: reference || null,
      },
    });
    onDone();
  });

  return (
    <form
      className="mt-2 flex flex-wrap items-end gap-2 rounded bg-ink-50 p-2.5"
      onSubmit={(event) => {
        event.preventDefault();
        receive.run();
      }}
    >
      <div className="w-32">
        <Field label={`Received (${line.unit})`} htmlFor={`qty-${line.id}`}>
          <input
            id={`qty-${line.id}`}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            className={inputClass}
          />
        </Field>
      </div>
      <div className="w-44">
        <Field label="Supplier document" htmlFor={`ref-${line.id}`}>
          <input
            id={`ref-${line.id}`}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="Challan / LR no"
            className={inputClass}
          />
        </Field>
      </div>
      <Button type="submit" variant="primary" disabled={receive.pending}>
        {receive.pending ? "Posting…" : "Post receipt"}
      </Button>
      {receive.error && (
        <p className="w-full text-sm text-critical-text">{receive.error.message}</p>
      )}
    </form>
  );
}

export default function PurchaseOrderDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<PurchaseOrderDetail>(
    `/purchase-orders/${params.id}`,
  );
  const [receiving, setReceiving] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  const provenance = data.eta_provenance;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Purchase orders", href: "/purchase-orders" }]}
        title={`${data.number} · ${data.supplier_name}`}
        description={`Ordered ${date(data.order_date)}`}
        actions={
          <Badge tone={data.days_late > 0 ? "bad" : "neutral"}>{humanise(data.status)}</Badge>
        }
      />

      <Card
        title="Why we believe this date"
        subtitle="Every change to a delivery date is stored with the evidence for it."
        className="mb-4"
      >
        <DefinitionList
          items={[
            {
              term: "Currently expected",
              value: (
                <span className="font-semibold">{date(provenance.current_expected_date)}</span>
              ),
              hint: dueText(provenance.current_expected_date),
            },
            {
              term: "Originally agreed",
              value: date(provenance.original_expected_date),
            },
            {
              term: "Revised",
              value: provenance.is_revised ? "Yes" : "No",
              hint: provenance.updated_at ? dateTime(provenance.updated_at) : undefined,
            },
          ]}
        />
        {provenance.is_revised ? (
          <div className="mt-3 rounded border border-high-border bg-high-bg px-3 py-2">
            <p className="text-sm text-high-text">{provenance.reason}</p>
            {provenance.source_message_excerpt && (
              <>
                <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-high-text">
                  From the supplier&apos;s own message
                </p>
                <pre className="mt-1 whitespace-pre-wrap rounded bg-white px-2.5 py-2 text-xs text-ink-700">
                  {provenance.source_message_excerpt}
                </pre>
              </>
            )}
          </div>
        ) : (
          <p className="mt-3 text-sm text-ink-600">
            No revision has been recorded. The date above is the one agreed when the order was
            placed.
          </p>
        )}
      </Card>

      <Card title="Lines">
        <Table
          caption="Purchase order lines"
          head={["#", "Material", "Ordered", "Received", "Rejected", "Outstanding", "Price", ""]}
        >
          {data.lines.map((line) => (
            // A fragment inside a map needs the key, or React cannot tell the
            // rows apart across renders.
            <Fragment key={line.id}>
              <tr>
                <Td>{line.line_no}</Td>
                <Td>
                  <span className="font-medium text-ink-900">{line.material_name}</span>
                  <span className="block font-mono text-xs text-ink-500">
                    {line.material_code}
                  </span>
                </Td>
                <Td numeric>{quantity(line.ordered_quantity, line.unit)}</Td>
                <Td numeric>{quantity(line.received_quantity, line.unit)}</Td>
                <Td numeric>{quantity(line.rejected_quantity, line.unit)}</Td>
                <Td numeric className="font-medium">
                  {quantity(line.outstanding_quantity, line.unit)}
                </Td>
                <Td numeric>{money(line.unit_price, data.currency)}</Td>
                <Td>
                  {Number(line.outstanding_quantity) > 0 && (
                    <Button
                      onClick={() => setReceiving(receiving === line.id ? null : line.id)}
                    >
                      {receiving === line.id ? "Cancel" : "Receive"}
                    </Button>
                  )}
                </Td>
              </tr>
              {receiving === line.id && (
                <tr>
                  <td colSpan={8} className="px-2 pb-3">
                    <ReceiveForm
                      line={line}
                      onDone={() => {
                        setReceiving(null);
                        reload();
                      }}
                    />
                  </td>
                </tr>
              )}
              {line.receipts.length > 0 && (
                <tr>
                  <td colSpan={8} className="px-2 pb-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                      Receipts
                    </p>
                    <ul className="mt-1 space-y-0.5 text-xs text-ink-600">
                      {line.receipts.map((receipt) => (
                        <li key={receipt.id}>
                          {dateTime(receipt.received_at)} —{" "}
                          {quantity(receipt.accepted_quantity, receipt.unit)} accepted
                          {Number(receipt.rejected_quantity) > 0 &&
                            `, ${quantity(receipt.rejected_quantity, receipt.unit)} rejected`}
                          {receipt.supplier_document_ref && ` · ${receipt.supplier_document_ref}`}
                          {receipt.note && ` · ${receipt.note}`}
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </Table>
      </Card>
    </>
  );
}

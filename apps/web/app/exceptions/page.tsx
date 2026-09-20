"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Select,
  SeverityBadge,
  Table,
  Td,
} from "@/components/ui";
import { dateTime, humanise, money, relativeAge } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ExceptionList } from "@/lib/types";

const SEVERITIES = [
  { value: "", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const STATUSES = [
  { value: "", label: "Open, investigating and proposed" },
  { value: "open", label: "Open" },
  { value: "investigating", label: "Investigating" },
  { value: "action_proposed", label: "Action proposed" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
];

const TYPES = [
  { value: "", label: "All types" },
  { value: "ORDER_AT_RISK", label: "Order at risk" },
  { value: "ORDER_LATE", label: "Order late" },
  { value: "MATERIAL_SHORTAGE", label: "Material shortage" },
  { value: "PO_LATE", label: "Purchase order late" },
  { value: "SUPPLIER_DELAY", label: "Supplier delay" },
  { value: "PRODUCTION_DELAY", label: "Production delay" },
  { value: "QC_FAILURE", label: "QC failure" },
  { value: "SHIPMENT_DELAY", label: "Shipment delay" },
  { value: "QUANTITY_MISMATCH", label: "Quantity mismatch" },
  { value: "INVENTORY_ANOMALY", label: "Inventory anomaly" },
];

export default function ExceptionsPage() {
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");

  const { data, error, loading, reload } = useApi<ExceptionList>("/exceptions", {
    severity,
    status,
    exception_type: type,
    include_closed: status ? true : false,
  });

  return (
    <>
      <PageHeader
        title="Command centre"
        description="Every open exception, ranked. Click one to see the evidence behind it."
      />

      <Card
        title="Filters"
        actions={
          data ? (
            <span className="text-xs text-ink-500">
              {data.total} shown
              {Object.entries(data.counts_by_severity)
                .filter(([, count]) => count > 0)
                .map(([key, count]) => ` · ${count} ${key}`)
                .join("")}
            </span>
          ) : null
        }
        className="mb-4"
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Select
            id="filter-severity"
            label="Severity"
            value={severity}
            onChange={setSeverity}
            options={SEVERITIES}
          />
          <Select
            id="filter-status"
            label="Status"
            value={status}
            onChange={setStatus}
            options={STATUSES}
          />
          <Select
            id="filter-type"
            label="Type"
            value={type}
            onChange={setType}
            options={TYPES}
          />
        </div>
      </Card>

      <Card title="Exceptions">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="No exceptions match these filters"
            description="Either the business is in good shape, or the filters are too narrow."
          />
        ) : (
          <Table
            caption="Operational exceptions"
            head={[
              "Severity",
              "Reference",
              "What happened",
              "Type",
              "Impact",
              "Status",
              "Detected",
            ]}
          >
            {data.items.map((item) => (
              <tr key={item.id} className="hover:bg-ink-50">
                <Td>
                  <SeverityBadge severity={item.severity} />
                </Td>
                <Td className="font-mono text-xs text-ink-500">{item.code}</Td>
                <Td className="max-w-md">
                  <Link
                    href={`/exceptions/${item.id}`}
                    className="font-medium text-ink-900 hover:underline"
                  >
                    {item.title}
                  </Link>
                  <p className="mt-0.5 line-clamp-2 text-xs text-ink-500">{item.summary}</p>
                </Td>
                <Td className="text-xs text-ink-600">{humanise(item.exception_type)}</Td>
                <Td className="max-w-xs text-xs text-ink-600">
                  {item.impact?.headline}
                  {item.impact?.financial.revenue_exposure && (
                    <span className="mt-0.5 block font-medium text-ink-800">
                      {money(
                        item.impact.financial.revenue_exposure,
                        item.impact.financial.currency,
                      )}{" "}
                      exposed
                    </span>
                  )}
                </Td>
                <Td>
                  <Badge
                    tone={
                      item.status === "resolved"
                        ? "ok"
                        : item.status === "dismissed"
                          ? "neutral"
                          : "warn"
                    }
                  >
                    {humanise(item.status)}
                  </Badge>
                </Td>
                <Td className="whitespace-nowrap text-xs text-ink-500" title={dateTime(item.detected_at)}>
                  {relativeAge(
                    (Date.now() - new Date(item.first_detected_at).getTime()) / 3_600_000,
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

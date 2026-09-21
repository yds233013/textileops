"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { IconCheckCircle } from "@/components/icons";
import {
  Card,
  EmptyState,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  RowLink,
  Segmented,
  Select,
  SEVERITY_EDGE,
  SeverityBadge,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { dateTime, money, relativeAge } from "@/lib/format";
import { useApi, useInitialParam } from "@/lib/hooks";
import { EXCEPTION_TYPE_LABEL, exceptionTypeLabel } from "@/lib/labels";
import type { ExceptionList } from "@/lib/types";

const STATUSES = [
  { value: "", label: "Active (open, investigating, proposed)" },
  { value: "open", label: "Open" },
  { value: "investigating", label: "Investigating" },
  { value: "action_proposed", label: "Action proposed" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
];

const TYPES = [
  { value: "", label: "Every kind" },
  ...Object.entries(EXCEPTION_TYPE_LABEL).map(([value, label]) => ({ value, label })),
];

type SeverityFilter = "" | "critical" | "high" | "medium" | "low";

export default function ExceptionsPage() {
  const [severity, setSeverity] = useState<SeverityFilter>("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const initialType = useInitialParam("type");
  useEffect(() => {
    if (initialType) setType(initialType);
  }, [initialType]);

  // Severity counts come from the unfiltered-by-severity set, so the numbers on
  // the segmented control do not collapse to one as soon as you pick one.
  const counts = useApi<ExceptionList>("/exceptions", {
    status,
    exception_type: type,
    include_closed: status ? true : false,
  });
  const { data, error, loading, reload } = useApi<ExceptionList>("/exceptions", {
    severity,
    status,
    exception_type: type,
    include_closed: status ? true : false,
  });
  const bySeverity = counts.data?.counts_by_severity ?? {};

  return (
    <>
      <PageHeader
        title="Exceptions"
        description="Everything the deterministic checks have flagged, ranked by how much it matters and how soon. Open one for the evidence, the cost and what to do."
      />

      <Card flush>
        <FilterBar
          summary={data ? `${data.total} ${data.total === 1 ? "exception" : "exceptions"}` : undefined}
        >
          <Segmented<SeverityFilter>
            label="Severity"
            value={severity}
            onChange={setSeverity}
            options={[
              { value: "", label: "All", count: counts.data?.total },
              { value: "critical", label: "Critical", count: bySeverity.critical ?? 0 },
              { value: "high", label: "High", count: bySeverity.high ?? 0 },
              { value: "medium", label: "Medium", count: bySeverity.medium ?? 0 },
              { value: "low", label: "Low", count: bySeverity.low ?? 0 },
            ]}
          />
          <Select id="filter-type" label="Kind" value={type} onChange={setType} options={TYPES} className="w-full sm:w-48" />
          <Select id="filter-status" label="Status" value={status} onChange={setStatus} options={STATUSES} className="w-full sm:w-64" />
        </FilterBar>

        {loading && !data ? (
          <Loading rows={8} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={<IconCheckCircle />}
            title="No exceptions match these filters"
            description="Either this part of the business is in good shape, or the filters are narrower than you meant."
          />
        ) : (
          <Table
            caption="Operational exceptions"
            head={["Severity", "Exception", "Kind", "Affects", "Exposure", "Status", "Raised"]}
            align={["left", "left", "left", "left", "right", "left", "right"]}
          >
            {data.items.map((item) => {
              const financial = item.impact?.financial;
              const customers = item.impact?.customers_affected ?? [];
              return (
                <RowLink key={item.id} href={`/exceptions/${item.id}`}>
                  <Td nowrap className="relative">
                    <span aria-hidden className={`absolute inset-y-2 left-0 w-[3px] rounded-r ${SEVERITY_EDGE[item.severity]}`} />
                    <SeverityBadge severity={item.severity} />
                  </Td>
                  <Td className="min-w-[22rem] max-w-xl">
                    <Link href={`/exceptions/${item.id}`} className="font-medium text-ink-950 group-hover:text-brand-700">
                      {item.title}
                    </Link>
                    <p className="mt-0.5 line-clamp-1 text-xs text-ink-500" title={item.summary}>
                      {item.summary}
                    </p>
                  </Td>
                  <Td nowrap className="text-xs text-ink-600">
                    {exceptionTypeLabel(item.exception_type)}
                  </Td>
                  <Td className="max-w-[14rem] text-xs text-ink-600">
                    {customers.length === 0 ? (
                      <span className="text-ink-400">No customer order</span>
                    ) : (
                      <span className="line-clamp-2">{customers.join(", ")}</span>
                    )}
                  </Td>
                  <Td numeric className="text-xs">
                    {/* Showing nothing when the figure cannot be computed makes
                        an unknown exposure look like a zero one. */}
                    {financial?.revenue_exposure ? (
                      <span className="font-medium text-ink-900">
                        {money(financial.revenue_exposure, financial.currency)}
                        {financial.basis === "partial" && <span className="text-ink-400"> (partial)</span>}
                      </span>
                    ) : (
                      <span className="text-ink-400" title={financial?.note ?? undefined}>
                        Not available
                      </span>
                    )}
                  </Td>
                  <Td nowrap>
                    <StatusPill value={item.status} />
                    {/* "Resolved" looked identical whether a person fixed the
                        problem or the engine merely stopped detecting it. */}
                    {item.auto_resolved && (
                      <span
                        className="mt-0.5 block text-2xs text-ink-500"
                        title="The engine stopped detecting the condition; nobody confirmed a fix."
                      >
                        cleared on its own
                      </span>
                    )}
                  </Td>
                  <Td numeric className="text-xs text-ink-500" title={dateTime(item.first_detected_at)}>
                    {relativeAge((Date.now() - new Date(item.first_detected_at).getTime()) / 3_600_000)}
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

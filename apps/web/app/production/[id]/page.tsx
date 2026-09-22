"use client";

import Link from "@/components/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DefinitionList,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { date, dateTime, humanise, percent, quantity } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { BatchDetail, Inspection } from "@/lib/types";

export default function BatchDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<BatchDetail>(`/production/batches/${id}`);
  const inspections = useApi<Inspection[]>("/quality/inspections", { batch_id: id });

  const [confirming, setConfirming] = useState<"schedule" | "start" | "complete" | null>(null);
  const act = useAction(async (action: string) => {
    await apiFetch(`/production/batches/${id}/actions`, { body: { action } });
    setConfirming(null);
    reload();
  });

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const canSchedule = data.status === "planned";
  const canStart = ["planned", "scheduled", "blocked"].includes(data.status);
  const canComplete = ["in_progress", "rework"].includes(data.status);

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Production", href: "/production" }]}
        title={`${data.code} · ${data.fabric_name}`}
        description={`${humanise(data.stage)} · ${quantity(data.planned_quantity, data.unit)} planned`}
        actions={
          <>
            {canSchedule && (
              <Button onClick={() => setConfirming("schedule")} disabled={act.pending}>
                Schedule
              </Button>
            )}
            {canStart && (
              <Button onClick={() => setConfirming("start")} disabled={act.pending}>
                Start
              </Button>
            )}
            {canComplete && (
              <Button variant="primary" onClick={() => setConfirming("complete")} disabled={act.pending}>
                Mark complete
              </Button>
            )}
          </>
        }
      />

      {act.error && (
        <div className="mb-4">
          <ErrorState error={act.error} />
        </div>
      )}

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Card title="Schedule" className="lg:col-span-2">
          <DefinitionList
            items={[
              { term: "Status", value: <StatusPill value={data.status} /> },
              { term: "Planned start", value: date(data.planned_start) },
              { term: "Planned completion", value: date(data.planned_completion) },
              {
                term: "Estimated completion",
                value: data.estimated_completion ? (
                  date(data.estimated_completion)
                ) : (
                  <span className="text-critical-text">No achievable date</span>
                ),
                hint:
                  data.delay_days > 0 ? `${data.delay_days} days behind plan` : undefined,
              },
              {
                term: "Materials on site by",
                value: data.material_ready_date ? (
                  date(data.material_ready_date)
                ) : (
                  <span className="text-critical-text">Not covered</span>
                ),
              },
              {
                term: "Actual completion",
                value: data.actual_completion ? dateTime(data.actual_completion) : "—",
              },
              { term: "Priority", value: data.priority },
            ]}
          />
          {data.blocked_reason && (
            <p className="mt-3 rounded border border-critical-border bg-critical-bg px-3 py-2 text-sm text-critical-text">
              Blocked: {data.blocked_reason}
            </p>
          )}
          {data.notes && <p className="mt-3 text-sm text-ink-600">{data.notes}</p>}
        </Card>

        <Card title="Output">
          <DefinitionList
            items={[
              { term: "Good", value: quantity(data.output_quantity, data.unit) },
              { term: "Wastage", value: quantity(data.wastage_quantity, data.unit) },
              { term: "Rejected", value: quantity(data.rejected_quantity, data.unit) },
              { term: "Yield", value: data.yield_pct ? percent(data.yield_pct, 1) : "—" },
            ]}
          />
          {data.sales_order_id && (
            <p className="mt-3 text-sm">
              For{" "}
              <Link
                href={`/orders/${data.sales_order_id}`}
                className="font-medium text-ink-900 hover:underline"
              >
                {data.sales_order_number}
              </Link>{" "}
              <span className="text-ink-600">({data.customer_name})</span>
            </p>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Material requirements">
          {data.requirements.length === 0 ? (
            <EmptyState title="No bill of materials for this fabric" />
          ) : (
            <Table
              caption="Materials required"
              head={["Material", "Required", "Issued", "Outstanding", "By"]}
            >
              {data.requirements.map((requirement) => (
                <tr key={requirement.material_id}>
                  <Td>
                    <Link
                      href={`/inventory/${requirement.material_id}`}
                      className="text-ink-900 hover:underline"
                    >
                      {requirement.material_name}
                    </Link>
                  </Td>
                  <Td numeric>{quantity(requirement.required_quantity, requirement.unit)}</Td>
                  <Td numeric>{quantity(requirement.issued_quantity, requirement.unit)}</Td>
                  <Td numeric>{quantity(requirement.outstanding_quantity, requirement.unit)}</Td>
                  <Td className="whitespace-nowrap text-xs">{date(requirement.required_by)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Quality inspections">
          {inspections.loading && !inspections.data ? (
            <Loading />
          ) : !inspections.data || inspections.data.length === 0 ? (
            <EmptyState title="Not inspected yet" />
          ) : (
            <ul className="space-y-2">
              {inspections.data.map((inspection) => (
                <li key={inspection.id} className="rounded border border-ink-200 p-2.5">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-xs">{inspection.code}</span>
                    <StatusPill value={inspection.outcome} />
                    <span className="ml-auto text-xs text-ink-500">
                      {dateTime(inspection.inspected_at)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-ink-600">
                    {quantity(inspection.inspected_quantity, inspection.unit)} inspected ·{" "}
                    {quantity(inspection.accepted_quantity, inspection.unit)} accepted ·{" "}
                    {quantity(inspection.rejected_quantity, inspection.unit)} rejected
                  </p>
                  {inspection.notes && (
                    <p className="mt-1 text-xs text-ink-700">{inspection.notes}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Event log" className="mt-4">
        {data.events.length === 0 ? (
          <EmptyState title="No events recorded" />
        ) : (
          <ol className="space-y-2">
            {data.events.map((event) => (
              <li key={event.id} className="flex gap-3 text-sm">
                <span className="w-40 shrink-0 text-xs text-ink-500">
                  {dateTime(event.occurred_at)}
                </span>
                <span className="min-w-0">
                  <Badge tone="neutral">{humanise(event.event_type)}</Badge>{" "}
                  <span className="text-ink-700">{event.note}</span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
          <ConfirmDialog
        open={confirming !== null}
        title={
          confirming === "complete"
            ? `Mark ${data.code} complete`
            : confirming === "start"
              ? `Start ${data.code}`
              : `Schedule ${data.code}`
        }
        confirmLabel={confirming === "complete" ? "Mark complete" : confirming === "start" ? "Start" : "Schedule"}
        pending={act.pending}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && act.run(confirming)}
        body={
          confirming === "complete"
            ? "The batch closes and its materials are issued from stock — yarn, dye and chemicals leave the ledger. This cannot be undone from here."
            : confirming === "start"
              ? "The batch is recorded as running from now, and the plan reads it as started."
              : "The batch is committed to the production plan and its materials stay reserved for it."
        }
      />
</>
  );
}

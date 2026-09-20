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
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { dateTime, humanise, quantity } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Inspection, Measurement } from "@/lib/types";

const OUTCOMES = [
  { value: "", label: "All outcomes" },
  { value: "reject", label: "Rejected" },
  { value: "rework", label: "Rework" },
  { value: "conditional_pass", label: "Conditional pass" },
  { value: "pass", label: "Passed" },
  { value: "pending", label: "Pending" },
];

function MeasurementRow({ measurement }: { measurement: Measurement }) {
  const observed =
    measurement.observed_text ??
    (measurement.observed_value !== null
      ? `${measurement.observed_value}${measurement.unit_text ? ` ${measurement.unit_text}` : ""}`
      : "—");
  const tolerance =
    measurement.tolerance_low !== null || measurement.tolerance_high !== null
      ? `${measurement.tolerance_low ?? "—"} to ${measurement.tolerance_high ?? "—"}`
      : "judged by the inspector";
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 text-xs">
      <span className="font-medium text-ink-800">
        {measurement.label ?? humanise(measurement.kind)}
      </span>
      <span className="text-ink-700">{observed}</span>
      <span className="text-ink-500">
        (target {measurement.target_value ?? "—"}, tolerance {tolerance})
      </span>
      <Badge
        tone={
          measurement.result === "out_of_tolerance"
            ? "bad"
            : measurement.result === "within_tolerance"
              ? "ok"
              : "neutral"
        }
      >
        {humanise(measurement.result)}
      </Badge>
    </li>
  );
}

export default function QualityPage() {
  const [outcome, setOutcome] = useState("");
  const { data, error, loading, reload } = useApi<Inspection[]>("/quality/inspections", {
    outcome,
  });

  return (
    <>
      <PageHeader
        title="Quality"
        description="Inspections and their consequences. A failure quarantines stock and changes what
          the customer can be promised."
      />

      <Card className="mb-4">
        <div className="max-w-xs">
          <Select
            id="qc-outcome"
            label="Outcome"
            value={outcome}
            onChange={setOutcome}
            options={OUTCOMES}
          />
        </div>
      </Card>

      <Card title="Inspections">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="No inspections match" />
        ) : (
          <Table
            caption="Quality inspections"
            head={["Reference", "Batch", "Outcome", "Inspected", "Accepted", "Rejected", "Findings", "When"]}
          >
            {data.map((inspection) => (
              <tr key={inspection.id}>
                <Td className="font-mono text-xs">
                  {inspection.code}
                  {inspection.reinspection_of_id && (
                    <span className="block text-ink-500">re-inspection</span>
                  )}
                </Td>
                <Td>
                  {inspection.production_batch_id ? (
                    <Link
                      href={`/production/${inspection.production_batch_id}`}
                      className="font-mono text-xs text-ink-900 hover:underline"
                    >
                      {inspection.batch_code}
                    </Link>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td>
                  <StatusPill value={inspection.outcome} />
                </Td>
                <Td numeric>{quantity(inspection.inspected_quantity, inspection.unit)}</Td>
                <Td numeric>{quantity(inspection.accepted_quantity, inspection.unit)}</Td>
                <Td numeric>
                  {Number(inspection.rejected_quantity) > 0 ? (
                    <span className="font-medium text-critical-text">
                      {quantity(inspection.rejected_quantity, inspection.unit)}
                    </span>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td className="max-w-md">
                  {inspection.notes && (
                    <p className="text-xs text-ink-700">{inspection.notes}</p>
                  )}
                  {inspection.measurements.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {inspection.measurements.map((measurement, index) => (
                        <MeasurementRow key={index} measurement={measurement} />
                      ))}
                    </ul>
                  )}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {dateTime(inspection.inspected_at)}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

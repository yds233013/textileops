"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { IconShield } from "@/components/icons";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  Segmented,
  StatusPill,
  type Tone,
} from "@/components/ui";
import { dateTime, humanise, num } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Inspection, Measurement } from "@/lib/types";

type Filter = "" | "reject" | "rework" | "conditional_pass" | "pass" | "pending";

/**
 * One measurement, stated no more strongly than it was taken. A value against
 * a numeric band is in or out of tolerance. A visual judgement with no band is
 * the inspector's call — shown with their words, never as "passed" and never
 * as "not assessed" when it plainly was. No reading at all is "not measured",
 * which is never treated as a pass.
 */
function measurementVerdict(m: Measurement): { label: string; tone: Tone } {
  if (m.result === "out_of_tolerance") return { label: "Out of tolerance", tone: "bad" };
  if (m.result === "within_tolerance") return { label: "Within tolerance", tone: "ok" };
  if (m.observed_text || m.observed_value) return { label: "Inspector's judgement", tone: "info" };
  return { label: "Not measured", tone: "neutral" };
}

function MeasurementRow({ m }: { m: Measurement }) {
  const verdict = measurementVerdict(m);
  const observed = m.observed_text ?? (m.observed_value !== null ? `${num(m.observed_value)}${m.unit_text ? ` ${m.unit_text}` : ""}` : null);
  const band =
    m.tolerance_low !== null || m.tolerance_high !== null
      ? `target ${m.target_value !== null ? num(m.target_value) : "—"}, accept ${m.tolerance_low !== null ? num(m.tolerance_low) : "—"}–${m.tolerance_high !== null ? num(m.tolerance_high) : "—"}`
      : null;
  return (
    <li className="grid grid-cols-[7rem_minmax(0,1fr)_auto] items-baseline gap-x-3 py-1.5 text-[13px]">
      <span className="font-medium text-ink-700">{m.label ?? (m.kind.length <= 3 ? m.kind.toUpperCase() : humanise(m.kind))}</span>
      <span className="min-w-0 text-ink-900">
        {observed ?? <span className="text-ink-400">No reading recorded</span>}
        {band && <span className="ml-2 text-xs text-ink-500">({band})</span>}
      </span>
      <Badge tone={verdict.tone}>{verdict.label}</Badge>
    </li>
  );
}

function Split({ inspection }: { inspection: Inspection }) {
  const total = Number(inspection.inspected_quantity) || 1;
  const ok = (Number(inspection.accepted_quantity) / total) * 100;
  const bad = (Number(inspection.rejected_quantity) / total) * 100;
  return (
    <div className="w-60">
      <div className="flex h-2 overflow-hidden rounded-full bg-ink-100">
        <span className="bg-good-solid" style={{ width: `${ok}%` }} />
        <span className="bg-critical-solid" style={{ width: `${bad}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-xs tnum">
        <span className="text-good-text">
          {num(inspection.accepted_quantity)} {inspection.unit} accepted
        </span>
        <span className={Number(inspection.rejected_quantity) > 0 ? "font-medium text-critical-text" : "text-ink-400"}>
          {num(inspection.rejected_quantity)} rejected
        </span>
      </div>
    </div>
  );
}

export default function QualityPage() {
  const [filter, setFilter] = useState<Filter>("");
  const { data, error, loading, reload } = useApi<Inspection[]>("/quality/inspections");
  const all = useMemo(() => data ?? [], [data]);
  const count = (o: string) => all.filter((i) => i.outcome === o).length;
  const shown = useMemo(() => (filter ? all.filter((i) => i.outcome === filter) : all), [all, filter]);

  return (
    <>
      <PageHeader
        title="Quality"
        description="Every inspection and what it did. Rejected cloth leaves the sellable pool; accepted cloth is released; a pending inspection is never treated as a pass."
      />

      <Card flush>
        <FilterBar summary={data ? `${shown.length} ${shown.length === 1 ? "inspection" : "inspections"}` : undefined}>
          <Segmented<Filter>
            label="Outcome"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "", label: "All", count: all.length },
              { value: "reject", label: "Rejected", count: count("reject") },
              { value: "rework", label: "Rework", count: count("rework") },
              { value: "conditional_pass", label: "Conditional", count: count("conditional_pass") },
              { value: "pass", label: "Passed", count: count("pass") },
              { value: "pending", label: "Awaiting verdict", count: count("pending") },
            ]}
          />
        </FilterBar>

        {loading && !data ? (
          <Loading rows={3} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState icon={<IconShield />} title="No inspections here" description="Inspections are recorded against a production batch or a stock lot." />
        ) : (
          <ul className="divide-y divide-ink-100">
            {shown.map((inspection) => (
              <li key={inspection.id} className="px-4 py-4">
                <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
                  <div className="min-w-[12rem]">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink-950">{inspection.code}</span>
                      <StatusPill value={inspection.outcome} />
                    </div>
                    <p className="mt-1 text-xs text-ink-500">
                      {inspection.batch_code ? (
                        <>
                          Batch{" "}
                          <Link href={`/production/${inspection.production_batch_id}`} className="font-medium text-ink-800 hover:text-brand-700">
                            {inspection.batch_code}
                          </Link>
                        </>
                      ) : (
                        "Stock lot"
                      )}{" "}
                      · {dateTime(inspection.inspected_at)}
                      {inspection.reinspection_of_id && " · re-inspection"}
                    </p>
                  </div>
                  <Split inspection={inspection} />
                  <p className="text-xs text-ink-500 tnum">
                    {num(inspection.inspected_quantity)} {inspection.unit} inspected
                  </p>
                </div>
                {inspection.notes && (
                  <p className="mt-3 max-w-prose text-[13px] leading-5 text-ink-800">{inspection.notes}</p>
                )}
                {inspection.measurements.length > 0 && (
                  <ul className="mt-2 max-w-3xl divide-y divide-ink-50 rounded-md border border-ink-150 px-3">
                    {inspection.measurements.map((m, index) => (
                      <MeasurementRow key={index} m={m} />
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

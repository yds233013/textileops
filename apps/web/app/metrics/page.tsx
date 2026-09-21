"use client";

import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Table,
  Td,
} from "@/components/ui";
import { humanise } from "@/lib/format";
import { exceptionTypeLabel } from "@/lib/labels";

/** 1199.71 minutes → "20 h"; 0.05 minutes → "3 s". Durations read in the unit a person would use. */
function formatDuration(value: number | null, unit: string): string {
  if (value === null) return "—";
  if (unit !== "minutes") return `${value} ${unit}`;
  if (value < 1) return `${Math.round(value * 60)} s`;
  if (value < 90) return `${Math.round(value)} min`;
  if (value < 60 * 48) return `${(value / 60).toFixed(value < 600 ? 1 : 0)} h`;
  return `${(value / 1440).toFixed(1)} days`;
}
import { useApi } from "@/lib/hooks";
import type { ProductMetrics } from "@/lib/types";

export default function MetricsPage() {
  const { data, error, loading, reload } = useApi<ProductMetrics>("/metrics/product");

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title="Product metrics"
        description={`Observed counts and durations over the last ${data.window_days} days.`}
      />

      <p className="mb-4 rounded border border-ink-200 bg-white px-3 py-2 text-sm text-ink-700">
        {data.caveat}
      </p>

      <Card title="Counts" className="mb-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Object.entries(data.counters).map(([key, value]) => (
            <div key={key} className="rounded border border-ink-100 bg-ink-50 px-3 py-2">
              <dt className="text-xs text-ink-500">{humanise(key).replace(/ pct$/, " (%)")}</dt>
              <dd className="mt-0.5 text-xl font-semibold tabular-nums text-ink-900">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card
        title="Workflow durations"
        subtitle="The raw timings a real before/after study would be built on."
        className="mb-4"
      >
        <Table caption="Workflow durations" head={["Step", "Occurrences", "Median", "90th pct", "Note"]}>
          {data.durations.map((duration) => (
            <tr key={duration.label}>
              <Td>{duration.label}</Td>
              <Td numeric>{duration.count}</Td>
              <Td numeric>
                {formatDuration(duration.median, duration.unit)}
              </Td>
              <Td numeric>{formatDuration(duration.p90, duration.unit)}</Td>
              <Td className="text-xs text-ink-500">{duration.note ?? ""}</Td>
            </tr>
          ))}
        </Table>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="AI usage">
          {data.ai.calls === 0 ? (
            <EmptyState title="No model calls recorded in this window" />
          ) : (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-600">Calls</dt>
                <dd className="font-medium tabular-nums">{data.ai.calls}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">Produced by deterministic rules</dt>
                <dd className="font-medium tabular-nums">{data.ai.stubbed_share_pct}%</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">Median latency</dt>
                <dd className="font-medium tabular-nums">
                  {data.ai.median_latency_ms !== null ? `${data.ai.median_latency_ms} ms` : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">Tokens in / out</dt>
                <dd className="font-medium tabular-nums">
                  {data.ai.input_tokens ?? "—"} / {data.ai.output_tokens ?? "—"}
                </dd>
              </div>
              <div className="pt-2">
                <dt className="text-xs uppercase tracking-wide text-ink-500">By workflow</dt>
                <dd className="mt-1 space-y-0.5">
                  {Object.entries(data.ai.by_workflow).map(([workflow, count]) => (
                    <span key={workflow} className="flex justify-between text-xs">
                      <span className="text-ink-600">{humanise(workflow)}</span>
                      <span className="tabular-nums">{count}</span>
                    </span>
                  ))}
                </dd>
              </div>
            </dl>
          )}
        </Card>

        <Card title="Open exceptions by type">
          {Object.keys(data.exception_breakdown.by_type).length === 0 ? (
            <EmptyState title="No open exceptions" />
          ) : (
            <ul className="space-y-1 text-sm">
              {Object.entries(data.exception_breakdown.by_type)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <li key={type} className="flex items-center justify-between">
                    <span className="text-ink-700">{exceptionTypeLabel(type)}</span>
                    <span className="font-medium tabular-nums">{count}</span>
                  </li>
                ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

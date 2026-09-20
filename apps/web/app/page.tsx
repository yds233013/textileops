"use client";

import Link from "next/link";
import { useState } from "react";
import { AttentionCard } from "@/components/attention";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Dashboard, MetricTile } from "@/lib/types";

function Tile({ tile }: { tile: MetricTile }) {
  const tone: Record<string, string> = {
    neutral: "text-ink-900",
    good: "text-good-text",
    warn: "text-high-text",
    bad: "text-critical-text",
  };
  return (
    <div className="rounded-lg border border-ink-200 bg-white px-3 py-2.5">
      <p className="text-xs font-medium text-ink-500">{tile.label}</p>
      <p className={`mt-0.5 text-2xl font-semibold tabular-nums ${tone[tile.tone]}`}>
        {tile.value ?? "—"}
        {tile.unit && tile.value !== null ? (
          <span className="ml-0.5 text-base font-normal text-ink-500">{tile.unit}</span>
        ) : null}
      </p>
      {tile.hint && <p className="mt-0.5 text-xs leading-snug text-ink-500">{tile.hint}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { data, error, loading, reload } = useApi<Dashboard>("/dashboard");
  const [message, setMessage] = useState<string | null>(null);

  const recompute = useAction(async () => {
    const result = await apiFetch<{
      created: number;
      updated: number;
      auto_resolved: number;
      unchanged: number;
    }>("/exceptions/recompute", { method: "POST" });
    setMessage(
      `Recomputed: ${result.created} new, ${result.updated} updated, ` +
        `${result.auto_resolved} auto-resolved, ${result.unchanged} unchanged.`,
    );
    reload();
  });

  if (loading && !data) return <Loading label="Reading the state of the business" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={data.greeting}
        description={
          <>
            As of {dateTime(data.as_of)}.{" "}
            <span className={data.ai_mode === "model" ? "" : "text-ink-500"}>
              {data.ai_note}
            </span>
          </>
        }
        actions={
          <Button onClick={() => recompute.run()} disabled={recompute.pending}>
            {recompute.pending ? "Recomputing…" : "Recompute exceptions"}
          </Button>
        }
      />

      {message && (
        <p className="mb-4 rounded border border-ink-200 bg-white px-3 py-2 text-sm text-ink-700">
          {message}
        </p>
      )}
      {recompute.error && (
        <div className="mb-4">
          <ErrorState error={recompute.error} />
        </div>
      )}

      <section aria-label="Business metrics" className="mb-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {data.metrics.map((tile) => (
            <Tile key={tile.key} tile={tile} />
          ))}
        </div>
      </section>

      <section aria-label="Attention queue">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-ink-900">
            Attention queue
            <span className="ml-2 font-normal text-ink-500">
              ranked by severity, urgency and customer
            </span>
          </h2>
          <Link href="/exceptions" className="text-sm text-ink-700 hover:underline">
            Open the command centre →
          </Link>
        </div>

        {data.attention_queue.length === 0 ? (
          <Card>
            <EmptyState
              title="Nothing needs your attention right now"
              description="Every open order, purchase order, batch and shipment is within its expected
                bounds. TextileOps keeps checking; anything new will appear here."
            />
          </Card>
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {data.attention_queue.map((card) => (
              <AttentionCard key={card.exception_id} card={card} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

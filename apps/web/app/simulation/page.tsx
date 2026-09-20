"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import type { SimulationResult } from "@/lib/types";

interface EventCatalogue {
  enabled: boolean;
  events: { key: string; label: string; description: string }[];
}

export default function SimulationPage() {
  const { data, error, loading } = useApi<EventCatalogue>("/simulation/events");
  const [results, setResults] = useState<SimulationResult[]>([]);

  const fire = useAction(async (event: string) => {
    const result = await apiFetch<SimulationResult>("/simulation/run", { body: { event } });
    setResults((previous) => [result, ...previous]);
  });

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader
        title="Simulation"
        description="Fire a realistic operational event and watch the exception engine recompute the
          business. These run through the real code paths — a simulated supplier delay is a real
          message through the real ingestion pipeline."
      />

      {!data?.enabled && (
        <p className="mb-4 rounded border border-medium-border bg-medium-bg px-3 py-2 text-sm text-medium-text">
          Simulation is disabled in this environment.
        </p>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data?.events.map((event) => (
          <Card key={event.key} title={event.label}>
            <p className="text-sm text-ink-600">{event.description}</p>
            <div className="mt-3">
              <Button
                variant="primary"
                onClick={() => fire.run(event.key)}
                disabled={!data.enabled || fire.pending}
              >
                {fire.pending ? "Running…" : "Fire event"}
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {fire.error && (
        <div className="mb-4">
          <ErrorState error={fire.error} />
        </div>
      )}

      <Card title="What happened">
        {results.length === 0 ? (
          <EmptyState
            title="No events fired yet"
            description="Fire one above to see the exception engine respond."
          />
        ) : (
          <ol className="space-y-3">
            {results.map((result, index) => (
              <li key={index} className="rounded border border-ink-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{result.event}</Badge>
                  <span className="text-sm font-medium text-ink-900">{result.summary}</span>
                </div>
                <p className="mt-1.5 text-xs text-ink-600">
                  Exception engine: {result.engine.created} created, {result.engine.updated}{" "}
                  updated, {result.engine.auto_resolved} auto-resolved, {result.engine.unchanged}{" "}
                  unchanged.
                </p>
                <pre className="mt-2 overflow-x-auto rounded bg-ink-50 px-2.5 py-2 text-xs text-ink-600">
                  {JSON.stringify(result.details, null, 2)}
                </pre>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}

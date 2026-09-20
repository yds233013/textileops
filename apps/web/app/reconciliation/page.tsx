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
  inputClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, humanise, percent } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { ReconciliationItem } from "@/lib/types";

function Item({ item, onResolved }: { item: ReconciliationItem; onResolved: () => void }) {
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");

  const resolve = useAction(async (dismiss: boolean) => {
    await apiFetch(`/reconciliation/${item.id}/resolve`, {
      body: {
        entity_id: choice || null,
        entity_type: choice ? "material" : null,
        value: note || null,
        note,
        dismiss,
      },
    });
    onResolved();
  });

  return (
    <li className="rounded border border-ink-200 p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <Badge tone="warn">{humanise(item.kind)}</Badge>
        <span className="ml-auto text-xs text-ink-500">{dateTime(item.created_at)}</span>
      </div>
      <p className="mt-1.5 text-sm font-medium text-ink-900">{item.question}</p>
      {item.fact_raw_value && (
        <pre className="mt-1.5 whitespace-pre-wrap rounded bg-ink-50 px-2.5 py-1.5 text-xs text-ink-600">
          {item.fact_raw_value}
        </pre>
      )}

      {item.candidates && item.candidates.length > 0 ? (
        <fieldset className="mt-2">
          <legend className="text-xs font-medium text-ink-700">Candidates</legend>
          <div className="mt-1 space-y-1">
            {item.candidates.map((candidate) => (
              <label key={candidate.id} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name={`candidate-${item.id}`}
                  value={candidate.id}
                  checked={choice === candidate.id}
                  onChange={() => setChoice(candidate.id)}
                />
                <span className="text-ink-800">{candidate.label}</span>
                <span className="text-xs text-ink-500">
                  {percent(candidate.score)} similar
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      ) : (
        <p className="mt-2 text-xs text-ink-500">
          No candidates were close enough to offer. Record what is correct in the note.
        </p>
      )}

      <input
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="What did you decide, and why?"
        className={`${inputClass} mt-2`}
      />

      <div className="mt-2 flex gap-2">
        <Button
          variant="primary"
          onClick={() => resolve.run(false)}
          disabled={resolve.pending}
        >
          Resolve
        </Button>
        <Button onClick={() => resolve.run(true)} disabled={resolve.pending}>
          Not relevant
        </Button>
      </div>
      {resolve.error && (
        <p className="mt-2 text-sm text-critical-text">{resolve.error.message}</p>
      )}
    </li>
  );
}

export default function ReconciliationPage() {
  const { data, error, loading, reload } = useApi<ReconciliationItem[]>("/reconciliation", {
    status: "open",
  });

  return (
    <>
      <PageHeader
        title="Reconciliation queue"
        description="Questions TextileOps could not answer on its own. Nothing here has changed any
          record; the source document or message is kept either way."
      />
      <Card>
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title="Nothing is waiting on you"
            description="Everything ingested so far mapped cleanly to a record."
          />
        ) : (
          <ul className="space-y-3">
            {data.map((item) => (
              <Item key={item.id} item={item} onResolved={reload} />
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

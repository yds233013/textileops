"use client";

import { useState } from "react";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Select,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AuditEvent } from "@/lib/types";

const ACTORS = [
  { value: "", label: "Everyone" },
  { value: "user", label: "People" },
  { value: "ai", label: "AI" },
  { value: "system", label: "System" },
];

export default function AuditPage() {
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const { data, error, loading, reload } = useApi<AuditEvent[]>("/audit", {
    actor_type: actor,
    action,
  });

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every consequential change, who made it, and what it looked like before and
          after."
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select id="audit-actor" label="Actor" value={actor} onChange={setActor} options={ACTORS} />
          <div>
            <label htmlFor="audit-action" className="sr-only">
              Filter by action
            </label>
            <input
              id="audit-action"
              type="search"
              value={action}
              onChange={(event) => setAction(event.target.value)}
              placeholder="Action, e.g. eta_revised, approved, received…"
              className={inputClass}
            />
          </div>
        </div>
      </Card>

      <Card title="Events">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState title="No audit events match" />
        ) : (
          <Table caption="Audit events" head={["When", "Actor", "Action", "What happened", "Change"]}>
            {data.map((event) => (
              <tr key={event.id}>
                <Td className="whitespace-nowrap text-xs">{dateTime(event.occurred_at)}</Td>
                <Td>
                  <Badge
                    tone={
                      event.actor_type === "ai"
                        ? "warn"
                        : event.actor_type === "user"
                          ? "ok"
                          : "neutral"
                    }
                  >
                    {event.actor_type}
                  </Badge>
                  {event.actor_label && (
                    <span className="mt-0.5 block text-xs text-ink-500">{event.actor_label}</span>
                  )}
                </Td>
                <Td className="font-mono text-xs">{event.action}</Td>
                <Td className="max-w-lg text-sm text-ink-700">{event.summary}</Td>
                <Td className="max-w-xs">
                  {event.before || event.after ? (
                    <details>
                      <summary className="cursor-pointer text-xs text-ink-500">
                        before / after
                      </summary>
                      <pre className="mt-1 overflow-x-auto rounded bg-ink-50 px-2 py-1 text-[11px] text-ink-600">
                        {JSON.stringify({ before: event.before, after: event.after }, null, 2)}
                      </pre>
                    </details>
                  ) : (
                    <span className="text-xs text-ink-400">—</span>
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

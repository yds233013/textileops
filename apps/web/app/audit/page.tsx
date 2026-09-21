"use client";

import { useState } from "react";
import { actionLabel, ActorTag, actorName } from "@/components/audit";
import {
  Card,
  Drawer,
  EmptyState,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  Segmented,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { dateTime, humanise } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AuditEvent } from "@/lib/types";

type Actor = "" | "user" | "ai" | "system";

function Changes({ event }: { event: AuditEvent }) {
  const keys = Array.from(new Set([...Object.keys(event.before ?? {}), ...Object.keys(event.after ?? {})]));
  if (keys.length === 0) return <p className="text-[13px] text-ink-500">No field-level change recorded.</p>;
  const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left text-2xs uppercase tracking-wider text-ink-500">
          <th className="pb-1.5 font-semibold">Field</th>
          <th className="pb-1.5 font-semibold">Before</th>
          <th className="pb-1.5 font-semibold">After</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((key) => (
          <tr key={key} className="border-t border-ink-100 align-top">
            <td className="py-1.5 pr-3 text-ink-600">{humanise(key)}</td>
            <td className="break-all py-1.5 pr-3 text-ink-500">{show(event.before?.[key])}</td>
            <td className="break-all py-1.5 font-medium text-ink-900">{show(event.after?.[key])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AuditPage() {
  const [actor, setActor] = useState<Actor>("");
  const [action, setAction] = useState("");
  const [open, setOpen] = useState<AuditEvent | null>(null);
  const { data, error, loading, reload } = useApi<AuditEvent[]>("/audit", { actor_type: actor, action, limit: 300 });

  return (
    <>
      <PageHeader
        title="Audit trail"
        description="Every consequential change: what happened, who or what did it, and what it looked like before and after. Nothing here can be edited or deleted."
      />
      <Card flush>
        <FilterBar summary={data ? `${data.length} ${data.length === 1 ? "event" : "events"}${data.length >= 300 ? " (most recent)" : ""}` : undefined}>
          <Segmented<Actor>
            label="Who"
            value={actor}
            onChange={setActor}
            options={[
              { value: "", label: "Everyone" },
              { value: "user", label: "People" },
              { value: "ai", label: "Investigations" },
              { value: "system", label: "Engine and system" },
            ]}
          />
          <div className="w-full sm:w-64">
            <label htmlFor="audit-action" className="sr-only">
              Filter by kind of event
            </label>
            <input
              id="audit-action"
              value={action}
              onChange={(event) => setAction(event.target.value)}
              placeholder="Filter: approved, received, eta…"
              className={inputClass}
            />
          </div>
        </FilterBar>
        {loading && !data ? (
          <Loading rows={10} />
        ) : error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        ) : !data || data.length === 0 ? (
          <EmptyState title="No events match" />
        ) : (
          <Table caption="Audit events" head={["When", "Who", "What", "", ""]} align={["left", "left", "left", "left", "right"]}>
            {data.map((event) => (
              <tr key={event.id} className="hover:bg-ink-25">
                <Td nowrap className="w-32 text-xs text-ink-500 tnum">{dateTime(event.occurred_at)}</Td>
                <Td nowrap className="w-56">
                  <span className="flex items-center gap-2">
                    <ActorTag event={event} />
                    <span className="truncate text-[13px] text-ink-800">{actorName(event)}</span>
                  </span>
                </Td>
                <Td nowrap className="w-44 text-xs font-medium text-ink-600">{actionLabel(event.action)}</Td>
                <Td className="text-ink-900">{event.summary}</Td>
                <Td nowrap className="w-24">
                  {(event.before || event.after) && (
                    <button type="button" onClick={() => setOpen(event)} className="text-xs font-medium text-brand-700 hover:text-brand-900">
                      Changes
                    </button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Drawer open={open !== null} title={open ? actionLabel(open.action) : ""} onClose={() => setOpen(null)}>
        {open && (
          <div className="space-y-4">
            <p className="text-[14px] leading-6 text-ink-900">{open.summary}</p>
            <dl className="grid grid-cols-2 gap-3 text-[13px]">
              <div>
                <dt className="text-xs text-ink-500">When</dt>
                <dd className="text-ink-900">{dateTime(open.occurred_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-500">Who</dt>
                <dd className="text-ink-900">{actorName(open)}</dd>
              </div>
            </dl>
            <Changes event={open} />
            <p className="font-mono text-2xs text-ink-400">{open.action}</p>
          </div>
        )}
      </Drawer>
    </>
  );
}

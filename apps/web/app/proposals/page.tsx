"use client";

import Link from "next/link";
import { useState } from "react";
import { IconArrowRight, IconCheckCircle } from "@/components/icons";
import { Card, EmptyState, ErrorState, Loading, PageHeader, StatusPill, Tabs } from "@/components/ui";
import { ago } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { actionTypeLabel } from "@/lib/labels";
import { originText } from "@/components/proposals";
import type { Proposal } from "@/lib/types";

type View = "pending_approval" | "done" | "all";

const DONE = new Set(["executed", "awaiting_external", "approved", "rejected", "failed", "expired", "cancelled"]);

export default function ProposalsPage() {
  const [view, setView] = useState<View>("pending_approval");
  const { data, error, loading, reload } = useApi<Proposal[]>("/proposals");
  const all = data ?? [];
  const pending = all.filter((p) => p.status === "pending_approval");
  const done = all.filter((p) => DONE.has(p.status));
  const shown = view === "pending_approval" ? pending : view === "done" ? done : all;

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Actions proposed by investigations and by people. Nothing here has happened yet — approving is what makes it real, and every decision is recorded against a name."
      />

      <div className="mb-4">
        <Tabs<View>
          label="Proposals"
          value={view}
          onChange={setView}
          tabs={[
            { value: "pending_approval", label: "Awaiting approval", count: pending.length },
            { value: "done", label: "Decided", count: done.length },
            { value: "all", label: "All", count: all.length },
          ]}
        />
      </div>

      {loading && !data ? (
        <Card flush>
          <Loading rows={4} />
        </Card>
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : shown.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconCheckCircle />}
            title={view === "pending_approval" ? "Nothing is waiting for you" : "Nothing here yet"}
            description="Proposals appear when an investigation suggests an action that passes the deterministic checks, or when someone raises one."
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {shown.map((proposal) => (
            <li key={proposal.id}>
              <Link
                href={`/proposals/${proposal.id}`}
                className="group block rounded-lg border border-ink-150 bg-white px-4 py-3.5 shadow-card transition hover:border-brand-200 hover:shadow-raised"
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-xs font-semibold text-brand-700">{actionTypeLabel(proposal.action_type)}</span>
                  <span className="text-xs text-ink-300">·</span>
                  <span className="text-xs text-ink-500">
                    {proposal.execution_mode === "internal" ? "TextileOps carries it out" : "A draft for a person to send"}
                  </span>
                  <span className="ml-auto">
                    <StatusPill value={proposal.status} />
                  </span>
                </div>
                <p className="mt-1 text-[14px] font-semibold text-ink-950 group-hover:text-brand-800">{proposal.title}</p>
                <p className="mt-0.5 line-clamp-2 max-w-prose text-[13px] leading-5 text-ink-600">{proposal.rationale}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-500">
                  <span>{originText(proposal)}</span>
                  <span>{ago(proposal.created_at)}</span>
                  {proposal.exception_code && (
                    <span className="truncate">
                      About: <span className="text-ink-700">{proposal.exception_title ?? proposal.exception_code}</span>
                    </span>
                  )}
                  {proposal.approvals[0] && (
                    <span>
                      {proposal.approvals[0].decision === "approved" ? "Approved" : "Rejected"} by{" "}
                      <span className="text-ink-700">{proposal.approvals[0].decided_by_name ?? "a person"}</span>
                    </span>
                  )}
                  <span className="ml-auto inline-flex items-center gap-1 font-medium text-brand-700">
                    {proposal.status === "pending_approval" ? "Review" : "Open"} <IconArrowRight size={12} />
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

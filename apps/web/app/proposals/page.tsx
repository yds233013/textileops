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
  Table,
  Td,
} from "@/components/ui";
import { dateTime, humanise } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Proposal } from "@/lib/types";

const STATUSES = [
  { value: "pending_approval", label: "Awaiting approval" },
  { value: "", label: "All" },
  { value: "approved", label: "Approved" },
  { value: "awaiting_external", label: "Approved, awaiting external send" },
  { value: "executed", label: "Executed" },
  { value: "rejected", label: "Rejected" },
  { value: "failed", label: "Failed" },
  { value: "expired", label: "Expired" },
];

export default function ProposalsPage() {
  const [status, setStatus] = useState("pending_approval");
  const { data, error, loading, reload } = useApi<Proposal[]>("/proposals", { status });

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Proposed actions. Nothing here has happened yet — approving is what makes it real."
      />

      <Card className="mb-4">
        <div className="max-w-xs">
          <Select
            id="proposal-status"
            label="Status"
            value={status}
            onChange={setStatus}
            options={STATUSES}
          />
        </div>
      </Card>

      <Card title="Proposals">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title="Nothing is waiting for you"
            description="Proposals appear here when an investigation or an operator suggests an action."
          />
        ) : (
          <Table
            caption="Action proposals"
            head={["Reference", "Action", "What it would do", "Origin", "Effect", "Status", "Raised"]}
          >
            {data.map((proposal) => (
              <tr key={proposal.id} className="hover:bg-ink-50">
                <Td className="font-mono text-xs text-ink-500">{proposal.code}</Td>
                <Td>
                  <Link
                    href={`/proposals/${proposal.id}`}
                    className="font-medium text-ink-900 hover:underline"
                  >
                    {proposal.title}
                  </Link>
                </Td>
                <Td className="max-w-sm text-xs text-ink-600">{proposal.rationale}</Td>
                <Td>
                  <Badge tone={proposal.origin === "ai_investigation" ? "warn" : "neutral"}>
                    {humanise(proposal.origin)}
                  </Badge>
                </Td>
                <Td>
                  <Badge tone={proposal.execution_mode === "internal" ? "ok" : "neutral"}>
                    {proposal.execution_mode === "internal"
                      ? "TextileOps executes"
                      : "Draft for you to send"}
                  </Badge>
                </Td>
                <Td>
                  <Badge tone={proposal.status === "pending_approval" ? "warn" : "neutral"}>
                    {humanise(proposal.status)}
                  </Badge>
                </Td>
                <Td className="whitespace-nowrap text-xs text-ink-500">
                  {dateTime(proposal.created_at)}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

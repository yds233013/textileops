"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DefinitionList,
  ErrorState,
  Loading,
  PageHeader,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, humanise } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Proposal } from "@/lib/types";

export default function ProposalDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<Proposal>(`/proposals/${id}`);
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (data) {
      setBody(data.draft_body ?? "");
      setSubject(data.draft_subject ?? "");
    }
  }, [data]);

  const saveDraft = useAction(async () => {
    await apiFetch(`/proposals/${id}/draft`, { method: "PATCH", body: { body, subject } });
    reload();
  });

  const decide = useAction(async (decision: "approve" | "reject") => {
    if (decision === "approve" && data?.draft_body && body !== data.draft_body) {
      await apiFetch(`/proposals/${id}/draft`, { method: "PATCH", body: { body, subject } });
    }
    const result = await apiFetch<{ message?: string }>(`/proposals/${id}/${decision}`, {
      body: { note },
    });
    setOutcome(result.message ?? "Recorded.");
    setConfirming(null);
    setNote("");
    reload();
  });

  if (loading && !data) return <Loading label="Opening the proposal" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const pending = data.status === "pending_approval";
  const execution = data.executions[data.executions.length - 1];

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Approvals", href: "/proposals" }]}
        title={data.title}
        description={data.rationale}
        actions={
          pending ? (
            <>
              <Button variant="primary" onClick={() => setConfirming("approve")}>
                Approve
              </Button>
              <Button variant="danger" onClick={() => setConfirming("reject")}>
                Reject
              </Button>
            </>
          ) : null
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge tone={pending ? "warn" : "neutral"}>{humanise(data.status)}</Badge>
        <Badge tone="neutral">{humanise(data.action_type)}</Badge>
        <Badge tone={data.origin === "ai_investigation" ? "warn" : "neutral"}>
          {humanise(data.origin)}
          {data.model ? ` · ${data.model}` : ""}
        </Badge>
        <span className="font-mono text-xs text-ink-400">{data.code}</span>
        {data.exception_id && (
          <Link
            href={`/exceptions/${data.exception_id}`}
            className="text-xs text-ink-600 hover:underline"
          >
            View the exception →
          </Link>
        )}
      </div>

      {outcome && (
        <p className="mb-4 rounded border border-good-border bg-good-bg px-3 py-2 text-sm text-good-text">
          {outcome}
        </p>
      )}
      {decide.error && (
        <div className="mb-4">
          <ErrorState error={decide.error} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card
            title="What approving this does"
            subtitle={data.effect_description}
          >
            <pre className="overflow-x-auto rounded bg-ink-50 px-3 py-2 text-xs text-ink-700">
              {JSON.stringify(data.payload, null, 2)}
            </pre>
          </Card>

          {data.draft_body !== null && (
            <Card
              title="Draft message"
              subtitle="TextileOps has no connected mailbox. Approving records the decision and leaves
                you this text to send yourself."
              actions={
                <>
                  <Button
                    onClick={() => {
                      navigator.clipboard?.writeText(
                        subject ? `Subject: ${subject}\n\n${body}` : body,
                      );
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </Button>
                  {pending && (
                    <Button onClick={() => saveDraft.run()} disabled={saveDraft.pending}>
                      {saveDraft.pending ? "Saving…" : "Save edits"}
                    </Button>
                  )}
                </>
              }
            >
              <div className="space-y-3">
                <div>
                  <label htmlFor="draft-subject" className="block text-xs font-medium text-ink-700">
                    Subject
                  </label>
                  <input
                    id="draft-subject"
                    value={subject}
                    disabled={!pending}
                    onChange={(event) => setSubject(event.target.value)}
                    className={`${inputClass} mt-1`}
                  />
                </div>
                <div>
                  <label htmlFor="draft-body" className="block text-xs font-medium text-ink-700">
                    Message
                  </label>
                  <textarea
                    id="draft-body"
                    value={body}
                    disabled={!pending}
                    rows={12}
                    onChange={(event) => setBody(event.target.value)}
                    className={`${inputClass} mt-1 font-mono text-xs leading-relaxed`}
                  />
                </div>
                {data.draft_edited && (
                  <p className="text-xs text-ink-500">
                    This draft has been edited by an operator. The original is kept in the record.
                  </p>
                )}
              </div>
            </Card>
          )}

          {execution && (
            <Card title="Execution">
              <DefinitionList
                items={[
                  { term: "Mode", value: humanise(execution.mode) },
                  { term: "Status", value: humanise(execution.status) },
                  { term: "Attempted", value: dateTime(execution.attempted_at) },
                  {
                    term: "Completed",
                    value: execution.completed_at ? dateTime(execution.completed_at) : "—",
                  },
                ]}
              />
              {execution.result && (
                <pre className="mt-3 overflow-x-auto rounded bg-ink-50 px-3 py-2 text-xs text-ink-700">
                  {JSON.stringify(execution.result, null, 2)}
                </pre>
              )}
              {execution.error && (
                <p className="mt-3 rounded border border-critical-border bg-critical-bg px-3 py-2 text-sm text-critical-text">
                  {execution.error}
                </p>
              )}
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card title="Decision history">
            {data.approvals.length === 0 ? (
              <p className="text-sm text-ink-500">No decision has been recorded yet.</p>
            ) : (
              <Table caption="Approvals" head={["Decision", "When", "Note"]}>
                {data.approvals.map((approval) => (
                  <tr key={approval.id}>
                    <Td>
                      <Badge tone={approval.decision === "approved" ? "ok" : "bad"}>
                        {humanise(approval.decision)}
                      </Badge>
                    </Td>
                    <Td className="whitespace-nowrap text-xs">
                      {dateTime(approval.decided_at)}
                    </Td>
                    <Td className="text-xs">{approval.note ?? "—"}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card title="Details">
            <DefinitionList
              items={[
                { term: "Raised", value: dateTime(data.created_at) },
                { term: "Expires", value: data.expires_at ? dateTime(data.expires_at) : "—" },
              ]}
            />
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={confirming !== null}
        title={confirming === "approve" ? "Approve this action" : "Reject this proposal"}
        pending={decide.pending}
        confirmLabel={confirming === "approve" ? "Approve" : "Reject"}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && decide.run(confirming)}
        body={
          <div className="space-y-2">
            <p>{confirming === "approve" ? data.effect_description : "Say why, for the record."}</p>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              className={inputClass}
              placeholder="Optional note"
            />
          </div>
        }
      />
    </>
  );
}

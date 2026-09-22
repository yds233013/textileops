"use client";

import Link from "@/components/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { IconArrowRight, IconCheckCircle } from "@/components/icons";
import { originText } from "@/components/proposals";
import {
  Alert,
  Button,
  Card,
  ConfirmDialog,
  Disclosure,
  ErrorState,
  Loading,
  PageHeader,
  StatusPill,
  Timeline,
  inputClass,
  textareaClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { ago, dateTime, humanise, num, shortDate } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import { actionTypeLabel } from "@/lib/labels";
import type { Proposal } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;

/** A result or payload value, as a person reads it. Identifiers stay out of prose. */
function readable(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return num(value);
  if (typeof value === "string") {
    if (/^-?\d+(\.\d+)?$/.test(value)) return num(value);
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return shortDate(value);
    return value;
  }
  return JSON.stringify(value);
}

export default function ProposalDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<Proposal>(`/proposals/${id}`);
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(null);
  const [outcome, setOutcome] = useState<{ text: string; kind: string } | null>(null);
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
    const result = await apiFetch<{ message?: string; outcome?: string }>(`/proposals/${id}/${decision}`, {
      body: { note },
    });
    setOutcome({ text: result.message ?? "Recorded.", kind: result.outcome ?? "ok" });
    setConfirming(null);
    setNote("");
    reload();
  });

  if (loading && !data) return <Loading variant="page" label="Opening the proposal" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const pending = data.status === "pending_approval";
  const execution = data.executions[data.executions.length - 1];
  const external = data.execution_mode === "external_draft";
  const edited = pending && data.draft_body !== null && (body !== (data.draft_body ?? "") || subject !== (data.draft_subject ?? ""));

  const history = [
    {
      key: "created",
      at: dateTime(data.created_at),
      title: "Proposed",
      detail: originText(data),
      tone: "neutral" as const,
    },
    ...data.approvals.map((approval) => ({
      key: approval.id,
      at: dateTime(approval.decided_at),
      title: approval.decision === "approved" ? `Approved by ${approval.decided_by_name ?? "a person"}` : `Rejected by ${approval.decided_by_name ?? "a person"}`,
      detail: approval.note ? `“${approval.note}”` : undefined,
      tone: approval.decision === "approved" ? ("ok" as const) : ("bad" as const),
    })),
    ...data.executions.map((ex) => ({
      key: ex.id,
      at: dateTime(ex.completed_at ?? ex.attempted_at),
      title:
        ex.status === "succeeded"
          ? "Carried out by TextileOps"
          : ex.status === "awaiting_external"
            ? "Draft ready — waiting for a person to send it"
            : ex.status === "failed"
              ? "Could not be carried out"
              : humanise(ex.status),
      detail: ex.error ?? undefined,
      tone: ex.status === "failed" ? ("bad" as const) : ex.status === "awaiting_external" ? ("warn" as const) : ("ok" as const),
    })),
  ];

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Approvals", href: "/proposals" }]}
        eyebrow={actionTypeLabel(data.action_type)}
        title={data.title}
        meta={
          <>
            <StatusPill value={data.status} />
            <span className="text-xs text-ink-500">{originText(data)} · {ago(data.created_at)}</span>
            <span className="font-mono text-2xs text-ink-400">{data.code}</span>
          </>
        }
        actions={
          pending ? (
            <>
              <Button variant="danger" onClick={() => setConfirming("reject")}>
                Reject
              </Button>
              <Button variant="primary" icon={<IconCheckCircle size={15} />} onClick={() => setConfirming("approve")}>
                {external ? "Approve draft" : "Approve and carry out"}
              </Button>
            </>
          ) : null
        }
      />

      {/* The request succeeding is not the same as the action succeeding: the
          banner takes its colour from what actually happened. */}
      {outcome && (
        <div className="mb-4">
          <Alert tone={outcome.kind === "failed" ? "bad" : outcome.kind === "awaiting_external" ? "warn" : "ok"}>
            {outcome.text}
          </Alert>
        </div>
      )}
      {decide.error && (
        <div className="mb-4">
          <ErrorState error={decide.error} />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <Card title="Why" subtitle="The case for doing this, as written by whoever proposed it.">
            <p className="max-w-prose text-[14px] leading-6 text-ink-800">{data.rationale}</p>
            {data.exception_id && (
              <Link
                href={`/exceptions/${data.exception_id}`}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-ink-50 px-2.5 py-1.5 text-[13px] text-ink-700 hover:bg-ink-100 hover:text-ink-950"
              >
                About: <span className="font-medium">{data.exception_title ?? data.exception_code}</span>
                <IconArrowRight size={13} />
              </Link>
            )}
          </Card>

          <Card title="What approving does">
            <div className={`rounded-md border px-3 py-2.5 text-[13.5px] ${external ? "border-medium-border bg-medium-bg text-medium-text" : "border-info-border bg-info-bg text-info-text"}`}>
              {data.effect_description}
            </div>
            <div className="mt-3">
              <Disclosure summary="Exact arguments the executor receives">
                <dl className="grid gap-x-6 gap-y-1.5 rounded-md bg-ink-50 px-3 py-2.5 text-xs sm:grid-cols-2">
                  {Object.entries(data.payload).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-3">
                      <dt className="text-ink-500">{humanise(key)}</dt>
                      <dd className={`text-right text-ink-800 ${typeof value === "string" && UUID.test(value) ? "font-mono text-2xs text-ink-500" : "tnum"}`}>
                        {readable(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-1.5 text-xs text-ink-500">Checked against the exception it belongs to before it was offered to you, and validated again on approval.</p>
              </Disclosure>
            </div>
          </Card>

          {data.draft_body !== null && (
            <Card
              title="Draft message"
              subtitle={
                pending
                  ? "Edit it before approving if you like — the original stays on the record. TextileOps sends nothing; you will send this yourself."
                  : "TextileOps has no connected mailbox. This is the text to send."
              }
              actions={
                <>
                  <Button
                    size="sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(subject ? `Subject: ${subject}\n\n${body}` : body);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </Button>
                  {pending && (
                    <Button size="sm" onClick={() => saveDraft.run()} disabled={!edited} loading={saveDraft.pending}>
                      Save edits
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
                    className={`${textareaClass} mt-1 max-w-prose leading-6`}
                  />
                </div>
                {data.draft_edited && (
                  <p className="text-xs text-ink-500">Edited by an operator. The original draft is kept in the record.</p>
                )}
              </div>
            </Card>
          )}

          {execution && (
            <Card title="Outcome">
              <div className="flex items-center gap-2">
                <StatusPill value={execution.status} />
                <span className="text-xs text-ink-500">{dateTime(execution.completed_at ?? execution.attempted_at)}</span>
              </div>
              {execution.result && Object.keys(execution.result).length > 0 && (
                <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-2">
                  {Object.entries(execution.result)
                    .filter(([, value]) => !(typeof value === "string" && UUID.test(value)))
                    .map(([key, value]) => (
                      <div key={key} className="flex justify-between gap-3 border-b border-ink-50 py-1">
                        <dt className="text-ink-500">{humanise(key)}</dt>
                        <dd className="text-right font-medium text-ink-900 tnum">{readable(value)}</dd>
                      </div>
                    ))}
                </dl>
              )}
              {execution.error && (
                <div className="mt-3">
                  <Alert tone="bad" title="Not carried out">
                    {execution.error}
                  </Alert>
                </div>
              )}
            </Card>
          )}
        </div>

        <aside className="space-y-6">
          <Card title="Decision trail" subtitle="Who proposed it, who decided, and what happened.">
            <Timeline items={history} />
          </Card>
          <Card title="Rules that apply">
            <ul className="space-y-2 text-[13px] leading-5 text-ink-700">
              <li>Only a person can approve. Investigations and the rule engine can only propose.</li>
              <li>Whoever raised a proposal needs someone else to approve it; only an owner may approve their own.</li>
              <li>Approval is checked again at the moment of execution; if the situation has changed, it is refused and says why.</li>
              {data.expires_at && pending && <li>Lapses on {shortDate(data.expires_at)} if nobody decides.</li>}
            </ul>
          </Card>
        </aside>
      </div>

      <ConfirmDialog
        open={confirming !== null}
        title={confirming === "approve" ? (external ? "Approve this draft" : "Approve and carry this out") : "Reject this proposal"}
        pending={decide.pending}
        confirmLabel={confirming === "approve" ? "Approve" : "Reject"}
        tone={confirming === "reject" ? "danger" : "default"}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && decide.run(confirming)}
        body={
          <div className="space-y-2">
            <p>
              {confirming === "approve"
                ? data.effect_description
                : "The proposal is closed and nothing happens. Say why — it stays on the record."}
            </p>
            {confirming === "approve" && edited && <p className="text-xs text-medium-text">Your edits to the draft will be saved first.</p>}
            <label htmlFor="decision-note" className="sr-only">
              Note
            </label>
            <textarea
              id="decision-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              className={textareaClass}
              placeholder={confirming === "approve" ? "Optional note for the record" : "Reason"}
            />
          </div>
        }
      />
    </>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DefinitionList,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  SeverityBadge,
  StatusPill,
  Unavailable,
  inputClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { dateTime, humanise, money } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { ExceptionDetail, Investigation, Proposal } from "@/lib/types";

function ImpactPanel({ detail }: { detail: ExceptionDetail }) {
  const impact = detail.impact;
  if (!impact) return <EmptyState title="Impact has not been calculated yet" />;
  return (
    <>
      <p className="text-sm text-ink-800">{impact.headline}</p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {impact.metrics.map((metric) => (
          <div key={metric.key} className="rounded border border-ink-100 bg-ink-50 px-3 py-2">
            <dt className="text-xs font-medium text-ink-500">{metric.label}</dt>
            <dd className="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">
              {metric.basis === "unavailable" ? (
                <Unavailable reason={metric.note} />
              ) : (
                <>
                  {metric.value}
                  {metric.unit ? ` ${metric.unit}` : ""}
                </>
              )}
            </dd>
            {metric.basis === "unavailable" && metric.note && (
              <dd className="mt-1 text-xs leading-snug text-ink-500">{metric.note}</dd>
            )}
          </div>
        ))}
        <div className="rounded border border-ink-100 bg-ink-50 px-3 py-2">
          <dt className="text-xs font-medium text-ink-500">Revenue exposure</dt>
          <dd className="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">
            {impact.financial.revenue_exposure ? (
              money(impact.financial.revenue_exposure, impact.financial.currency)
            ) : (
              <Unavailable reason={impact.financial.note} />
            )}
          </dd>
          <dd className="mt-1 text-xs text-ink-500">
            {impact.financial.note ?? `Basis: ${impact.financial.basis}`}
          </dd>
        </div>
      </dl>

      {impact.affected_orders.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Customer orders affected
          </h3>
          <ul className="mt-1.5 space-y-1 text-sm">
            {impact.affected_orders.map((order) => (
              <li key={order.sales_order_id}>
                <Link
                  href={`/orders/${order.sales_order_id}`}
                  className="font-medium text-ink-900 hover:underline"
                >
                  {order.number}
                </Link>{" "}
                <span className="text-ink-600">
                  · {order.customer_name} · promised {order.promised_date} ·{" "}
                  {order.outstanding_value
                    ? money(order.outstanding_value, order.currency)
                    : "value not available"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {impact.notes.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-ink-600">
          {impact.notes.map((note, index) => (
            <li key={index}>· {note}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-ink-400">
        Calculated deterministically at {dateTime(impact.computed_at)}.
      </p>
    </>
  );
}

function InvestigationPanel({ investigation }: { investigation: Investigation }) {
  const findings = investigation.findings;
  if (!findings) {
    return (
      <p className="text-sm text-ink-600">
        {investigation.error ?? "This investigation produced no findings."}
      </p>
    );
  }
  return (
    <div className="space-y-4 text-sm">
      {investigation.is_stubbed && (
        <p className="rounded border border-medium-border bg-medium-bg px-3 py-2 text-xs text-medium-text">
          Produced by the deterministic rule engine because no model credentials are
          configured. It restates recorded evidence and does not reason beyond it.
        </p>
      )}

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          What happened
        </h3>
        <p className="mt-1 text-ink-800">{findings.what_happened}</p>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Root cause
        </h3>
        <p className="mt-1 text-ink-800">
          {findings.root_cause.statement}{" "}
          <Badge tone={findings.root_cause.kind === "established" ? "ok" : "warn"}>
            {findings.root_cause.kind === "established" ? "Established" : "Hypothesis"}
          </Badge>
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Operational impact
          </h3>
          <p className="mt-1 text-ink-800">{findings.operational_impact}</p>
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Financial impact
          </h3>
          <p className="mt-1 text-ink-800">{findings.financial_impact}</p>
        </div>
      </section>

      {findings.options.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Options
          </h3>
          <ul className="mt-1.5 space-y-2">
            {findings.options.map((option) => (
              <li key={option.title} className="rounded border border-ink-100 bg-ink-50 p-2.5">
                <p className="font-medium text-ink-900">{option.title}</p>
                <p className="text-ink-700">{option.description}</p>
                <p className="mt-1 text-xs text-ink-500">Trade-off: {option.trade_off}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {findings.evidence.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Evidence the investigator used
          </h3>
          <ul className="mt-1.5 space-y-1 text-xs text-ink-600">
            {findings.evidence.map((item, index) => (
              <li key={index}>
                <span className="font-medium text-ink-800">{item.label}</span> — {item.detail}{" "}
                <span className="text-ink-400">({item.source})</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {findings.missing_information.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            What is missing or uncertain
          </h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-700">
            {findings.missing_information.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      <footer className="border-t border-ink-100 pt-2 text-xs text-ink-500">
        {investigation.provider}
        {investigation.model ? ` · ${investigation.model}` : ""} ·{" "}
        {investigation.tool_calls?.length ?? 0} read-only tool call(s) ·{" "}
        confidence {Math.round(findings.confidence * 100)}%
        {investigation.tool_calls && investigation.tool_calls.length > 0 && (
          <span className="ml-1">
            ({investigation.tool_calls.map((call) => call.name).join(", ")})
          </span>
        )}
      </footer>
    </div>
  );
}

/** Evidence whose text was written by someone outside this business.
 *  Mirrors UNTRUSTED_EVIDENCE_KINDS in the backend's models/enums.py. */
const UNTRUSTED_EVIDENCE_KINDS = new Set(["message", "document", "ai_hypothesis"]);

export default function ExceptionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<ExceptionDetail>(`/exceptions/${id}`);
  const proposals = useApi<Proposal[]>("/proposals", { exception_id: id });
  const [closing, setClosing] = useState<"resolved" | "dismissed" | null>(null);
  const [note, setNote] = useState("");

  const investigate = useAction(async () => {
    await apiFetch(`/exceptions/${id}/investigate`, { method: "POST" });
    reload();
    proposals.reload();
  });

  const close = useAction(async (status: string, reason: string) => {
    await apiFetch(`/exceptions/${id}/status`, { body: { status, note: reason } });
    setClosing(null);
    setNote("");
    reload();
  });

  if (loading && !data) return <Loading label="Opening the exception" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const latest = data.investigations[0];
  const discarded = latest?.findings?.discarded_recommendations ?? [];
  const open = !["resolved", "dismissed"].includes(data.status);

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Command centre", href: "/exceptions" }]}
        title={data.title}
        description={data.summary}
        actions={
          <>
            <Button
              onClick={() => investigate.run()}
              disabled={investigate.pending}
              variant="primary"
            >
              {investigate.pending
                ? "Investigating…"
                : latest
                  ? "Investigate again"
                  : "Investigate"}
            </Button>
            {open && (
              <>
                <Button onClick={() => setClosing("resolved")}>Resolve</Button>
                <Button onClick={() => setClosing("dismissed")}>Dismiss</Button>
              </>
            )}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SeverityBadge severity={data.severity} />
        <Badge>{humanise(data.exception_type)}</Badge>
        {/* This rendered "Dismissed" in success green, because the only
            question asked was whether the exception was still open. Somebody
            deciding a problem did not matter is not the same as it being
            fixed. StatusPill carries the deliberate tone for each status. */}
        <StatusPill value={data.status} />
        <span className="font-mono text-xs text-ink-400">{data.code}</span>
        {data.auto_resolved && (
          <Badge tone="neutral" title="The engine stopped detecting the condition; nobody confirmed a fix.">
            Auto-resolved
          </Badge>
        )}
        {data.occurrence_count > 1 && (
          <Badge tone="neutral">Seen {data.occurrence_count} times</Badge>
        )}
      </div>

      {investigate.error && (
        <div className="mb-4">
          <ErrorState error={investigate.error} />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title="What it costs if nothing is done">
            <ImpactPanel detail={data} />
          </Card>

          {/* The old subtitle was "Every figure here came from our own
              records, not from a model." That is true of the calculations and
              flatly untrue of the message and document items, whose detail is
              a supplier's own prose copied verbatim — the very text the
              system fences before it goes anywhere near a model. A blanket
              assurance over a mixed list erases the distinction the whole
              untrusted-content invariant exists to hold. Each item now says
              where it came from, and the items that are somebody else's words
              are marked as such. */}
          <Card
            title="Evidence"
            subtitle="Calculations and records are ours. Quoted messages and documents are not — they are what a third party wrote."
          >
            {data.evidence.length === 0 ? (
              <EmptyState title="No evidence recorded" />
            ) : (
              <ol className="space-y-3">
                {data.evidence.map((item) => (
                  <li key={item.id} className="border-l-2 border-ink-200 pl-3">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-medium text-ink-900">{item.label}</span>
                      <Badge tone="neutral">{humanise(item.kind)}</Badge>
                      {UNTRUSTED_EVIDENCE_KINDS.has(item.kind) && (
                        <Badge tone="warn">Third-party text</Badge>
                      )}
                    </div>
                    <p
                      className={
                        UNTRUSTED_EVIDENCE_KINDS.has(item.kind)
                          ? "mt-0.5 whitespace-pre-wrap border-l-2 border-medium-border pl-2 text-sm italic text-ink-700"
                          : "mt-0.5 whitespace-pre-wrap text-sm text-ink-700"
                      }
                    >
                      {item.detail}
                    </p>
                    {item.data && (
                      <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-ink-500">
                        {Object.entries(item.data).map(([key, value]) => (
                          <div key={key}>
                            <dt className="inline">{humanise(key)}: </dt>
                            <dd className="inline font-medium tabular-nums text-ink-700">
                              {String(value)}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </Card>

          <Card
            title="Investigation"
            subtitle={
              latest
                ? `Last run ${dateTime(latest.started_at)}`
                : "Not investigated yet. The investigator is read-only: it can look, not change."
            }
          >
            {latest ? (
              <InvestigationPanel investigation={latest} />
            ) : (
              <EmptyState
                title="No investigation yet"
                description="Run one to get a written explanation, the options, and a drafted action
                  you can approve or reject."
              />
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Recommended action">
            <p className="text-sm text-ink-800">
              {data.recommended_action ?? "No recommendation recorded."}
            </p>
          </Card>

          <Card title="Proposals" subtitle="Nothing happens until you approve it.">
            {proposals.loading && !proposals.data ? (
              <Loading />
            ) : !proposals.data || proposals.data.length === 0 ? (
              <EmptyState
                title="No proposals yet"
                description={
                  !data.investigated_at
                    ? "Run an investigation, or raise a proposal yourself."
                    : discarded.length > 0
                      ? // Saying "it lists the options rather than picking one"
                        // was an invented reason: the investigation may well
                        // have recommended something that the deterministic
                        // gate then refused. Report what actually happened.
                        `The investigation recommended ${discarded.length} action(s) that were refused before reaching you: ${discarded
                          .map(
                            (d) =>
                              `${humanise(d.action_type)} — ${humanise(d.reason)}`,
                          )
                          .join("; ")}.`
                      : "The investigation did not recommend an action. Review its options and raise a proposal when you have decided."
                }
              />
            ) : (
              <ul className="space-y-2">
                {proposals.data.map((proposal) => (
                  <li key={proposal.id} className="rounded border border-ink-200 p-2.5">
                    <Link
                      href={`/proposals/${proposal.id}`}
                      className="text-sm font-medium text-ink-900 hover:underline"
                    >
                      {proposal.title}
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge tone={proposal.status === "pending_approval" ? "warn" : "neutral"}>
                        {humanise(proposal.status)}
                      </Badge>
                      <Badge tone="neutral">{humanise(proposal.action_type)}</Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Details">
            <DefinitionList
              items={[
                { term: "First detected", value: dateTime(data.first_detected_at) },
                { term: "Last evaluated", value: dateTime(data.last_evaluated_at) },
                {
                  term: "Resolved",
                  value: data.resolved_at ? dateTime(data.resolved_at) : "—",
                },
                { term: "Priority score", value: data.priority_score },
              ]}
            />
            {data.resolution_note && (
              <p className="mt-3 rounded bg-ink-50 px-2.5 py-2 text-sm text-ink-700">
                {data.resolution_note}
              </p>
            )}
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={closing !== null}
        title={closing === "resolved" ? "Resolve this exception" : "Dismiss this exception"}
        pending={close.pending}
        confirmLabel={closing === "resolved" ? "Resolve" : "Dismiss"}
        onCancel={() => setClosing(null)}
        onConfirm={() => closing && close.run(closing, note)}
        body={
          <div className="space-y-2">
            <p>
              {closing === "resolved"
                ? "Say what was done, so the next person reading this knows."
                : "Say why this is not worth acting on."}
            </p>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              className={inputClass}
              placeholder="e.g. Supplier confirmed dispatch this morning; material arrives Tuesday."
            />
            {close.error && <p className="text-sm text-critical-text">{close.error.message}</p>}
          </div>
        }
      />
    </>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { IconArrowRight, IconModel } from "@/components/icons";
import { actorName } from "@/components/audit";
import { InvestigationPanel } from "@/components/investigation";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  ProvenanceTag,
  SeverityBadge,
  StatusPill,
  Timeline,
  Unavailable,
  textareaClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { ago, dateTime, humanise, money, num, shortDate } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import { actionTypeLabel, exceptionTypeLabel } from "@/lib/labels";
import type { AuditEvent, Evidence, ExceptionDetail, ImpactMetric, Proposal } from "@/lib/types";

/** Evidence whose text was written by someone outside this business.
 *  Mirrors UNTRUSTED_EVIDENCE_KINDS in the backend's models/enums.py. */
const UNTRUSTED_EVIDENCE_KINDS = new Set(["message", "document", "ai_hypothesis"]);

const DISCARD_REASON: Record<string, string> = {
  not_an_action_textileops_can_take: "not an action TextileOps can take",
  named_an_entity_this_exception_is_not_about: "it named something this exception is not about",
  no_arguments_could_be_derived: "the details it needs could not be worked out",
  arguments_failed_validation: "its details failed validation",
  already_being_replaced: "the rejected cloth is already being remade",
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return num(value);
  if (typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value)) return num(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return shortDate(value);
  return String(value);
}

function MetricTile({ metric }: { metric: ImpactMetric }) {
  return (
    <div className="rounded-md border border-ink-150 bg-white px-3 py-2.5">
      <dt className="text-xs text-ink-500">{metric.label}</dt>
      <dd className="mt-0.5 text-[15px] font-semibold text-ink-950 tnum">
        {metric.basis === "unavailable" ? (
          <span className="text-[13px] font-medium">
            <Unavailable reason={metric.note} />
          </span>
        ) : (
          <>
            {formatValue(metric.value)}
            {metric.unit ? <span className="ml-1 text-[13px] font-medium text-ink-500">{metric.unit}</span> : null}
          </>
        )}
      </dd>
      {metric.note && <dd className="mt-1 text-xs leading-4 text-ink-500">{metric.note}</dd>}
    </div>
  );
}

function ImpactSection({ detail }: { detail: ExceptionDetail }) {
  const impact = detail.impact;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          What it costs if nothing changes <ProvenanceTag kind="fact" />
        </span>
      }
      subtitle={impact ? `Worked out by the impact engine ${ago(impact.computed_at)}. Figures that cannot be known say so.` : undefined}
    >
      {!impact ? (
        <EmptyState compact title="Impact has not been calculated yet" />
      ) : (
        <>
          <p className="max-w-prose text-[14px] font-medium leading-6 text-ink-900">{impact.headline}</p>
          <dl className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {impact.metrics
              .filter((m) => m.basis !== "unavailable")
              .map((metric) => (
                <MetricTile key={metric.key} metric={metric} />
              ))}
            <div className="rounded-md border border-ink-150 bg-white px-3 py-2.5">
              <dt className="text-xs text-ink-500">Revenue exposure</dt>
              <dd className="mt-0.5 text-[15px] font-semibold text-ink-950 tnum">
                {impact.financial.revenue_exposure ? (
                  <>
                    {money(impact.financial.revenue_exposure, impact.financial.currency)}
                    {impact.financial.basis === "partial" && (
                      <span className="ml-1 text-xs font-medium text-ink-500">(partial)</span>
                    )}
                  </>
                ) : (
                  <span className="text-[13px] font-medium">
                    <Unavailable reason={impact.financial.note} />
                  </span>
                )}
              </dd>
              {impact.financial.note && <dd className="mt-1 text-xs leading-4 text-ink-500">{impact.financial.note}</dd>}
            </div>
            {impact.metrics
              .filter((m) => m.basis === "unavailable")
              .map((metric) => (
                <MetricTile key={metric.key} metric={metric} />
              ))}
          </dl>

          {impact.affected_orders.length > 0 && (
            <div className="mt-4">
              <h3 className="text-2xs font-semibold uppercase tracking-wider text-ink-500">Customer orders affected</h3>
              <ul className="mt-1.5 divide-y divide-ink-100 rounded-md border border-ink-150">
                {impact.affected_orders.map((order) => (
                  <li key={order.sales_order_id}>
                    <Link
                      href={`/orders/${order.sales_order_id}`}
                      className="flex items-center gap-3 px-3 py-2 text-[13px] hover:bg-ink-25"
                    >
                      <span className="w-16 font-medium text-ink-950">{order.number}</span>
                      <span className="min-w-0 flex-1 truncate text-ink-700">{order.customer_name}</span>
                      <span className="text-xs text-ink-500">promised {shortDate(order.promised_date)}</span>
                      <span className="w-28 text-right font-medium text-ink-900 tnum">
                        {order.outstanding_value ? money(order.outstanding_value, order.currency) : (
                          <span className="text-xs font-normal text-ink-400">not priced</span>
                        )}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {impact.notes.length > 0 && (
            <ul className="mt-3 space-y-0.5 text-xs text-ink-500">
              {impact.notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

function EvidenceItem({ item }: { item: Evidence }) {
  const untrusted = UNTRUSTED_EVIDENCE_KINDS.has(item.kind);
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-ink-900">{item.label}</span>
        {untrusted ? (
          <ProvenanceTag kind={item.kind === "ai_hypothesis" ? "ai" : "source"} />
        ) : (
          <ProvenanceTag kind="fact" label={item.kind === "calculation" ? "Calculated" : "Record"} />
        )}
      </div>
      {untrusted ? (
        <blockquote className="mt-1.5 max-w-prose whitespace-pre-wrap border-l-2 border-source-border bg-source-bg/50 py-1.5 pl-3 pr-2 text-[13px] italic leading-5 text-ink-700">
          {item.detail}
        </blockquote>
      ) : (
        <p className="mt-1 max-w-prose whitespace-pre-wrap text-[13px] leading-5 text-ink-700">{item.detail}</p>
      )}
      {item.data && Object.keys(item.data).length > 0 && (
        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-ink-500">
          {Object.entries(item.data).map(([key, value]) => (
            <div key={key}>
              <dt className="inline">{humanise(key)} </dt>
              <dd className="inline font-medium text-ink-800 tnum">{formatValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

const LINKS: { key: keyof ExceptionDetail; label: string; href: (id: string) => string }[] = [
  { key: "sales_order_id", label: "Customer order", href: (id) => `/orders/${id}` },
  { key: "purchase_order_id", label: "Purchase order", href: (id) => `/purchase-orders/${id}` },
  { key: "production_batch_id", label: "Production batch", href: (id) => `/production/${id}` },
  { key: "material_id", label: "Material coverage", href: (id) => `/inventory/${id}` },
  { key: "supplier_id", label: "Supplier", href: (id) => `/suppliers/${id}` },
  { key: "shipment_id", label: "Shipments", href: () => `/shipments` },
];

export default function ExceptionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data, error, loading, reload } = useApi<ExceptionDetail>(`/exceptions/${id}`);
  const proposals = useApi<Proposal[]>("/proposals", { exception_id: id, status: "" });
  const history = useApi<AuditEvent[]>("/audit", { exception_id: id, limit: 50 });
  const [closing, setClosing] = useState<"resolved" | "dismissed" | null>(null);
  const [note, setNote] = useState("");

  const investigate = useAction(async () => {
    await apiFetch(`/exceptions/${id}/investigate`, { method: "POST" });
    reload();
    proposals.reload();
    history.reload();
  });

  const close = useAction(async (status: string, reason: string) => {
    await apiFetch(`/exceptions/${id}/status`, { body: { status, note: reason } });
    setClosing(null);
    setNote("");
    reload();
    history.reload();
  });

  if (loading && !data) return <Loading variant="page" label="Opening the exception" />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const latest = data.investigations[0];
  const discarded = latest?.findings?.discarded_recommendations ?? [];
  const open = !["resolved", "dismissed"].includes(data.status);
  const links = LINKS.filter((link) => Boolean(data[link.key]));
  const pending = (proposals.data ?? []).filter((p) => p.status === "pending_approval");

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Exceptions", href: "/exceptions" }]}
        title={data.title}
        meta={
          <>
            <SeverityBadge severity={data.severity} />
            <Badge>{exceptionTypeLabel(data.exception_type)}</Badge>
            {/* Dismissed is not fixed: StatusPill carries a deliberate tone per status. */}
            <StatusPill value={data.status} />
            {data.auto_resolved && (
              <Badge title="The engine stopped detecting the condition; nobody confirmed a fix.">Cleared on its own</Badge>
            )}
            <span className="text-xs text-ink-500">
              Raised {ago(data.first_detected_at)}
              {data.occurrence_count > 1 ? ` · seen ${data.occurrence_count} times` : ""}
            </span>
            <span className="font-mono text-2xs text-ink-400">{data.code}</span>
          </>
        }
        actions={
          <>
            {open && (
              <>
                <Button onClick={() => setClosing("dismissed")}>Dismiss</Button>
                <Button onClick={() => setClosing("resolved")}>Mark resolved</Button>
              </>
            )}
            <Button
              onClick={() => investigate.run()}
              loading={investigate.pending}
              variant={latest ? "secondary" : "primary"}
              icon={<IconModel size={14} />}
            >
              {investigate.pending ? "Investigating…" : latest ? "Investigate again" : "Investigate"}
            </Button>
          </>
        }
      />

      {investigate.error && (
        <div className="mb-4">
          <ErrorState error={investigate.error} />
        </div>
      )}

      {/* What happened / why it matters, before anything else. */}
      <div className="mb-6 grid gap-4 rounded-lg border border-ink-150 bg-white p-4 shadow-card md:grid-cols-2">
        <div>
          <h2 className="text-2xs font-semibold uppercase tracking-wider text-ink-500">What happened</h2>
          <p className="mt-1 max-w-prose text-[14px] leading-6 text-ink-900">{data.summary}</p>
        </div>
        <div className="md:border-l md:border-ink-100 md:pl-4">
          <h2 className="text-2xs font-semibold uppercase tracking-wider text-ink-500">Recommended next step</h2>
          <p className="mt-1 max-w-prose text-[14px] leading-6 text-ink-900">
            {data.recommended_action ?? "No recommendation is recorded for this kind of exception."}
          </p>
          <p className="mt-1 text-xs text-ink-500">From the rule that raised it. Deterministic, not a model.</p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <ImpactSection detail={data} />

          {/* Evidence is not uniformly ours: calculations and records came out
              of our own database, messages and documents are a third party's
              words copied verbatim. Each item says which, on its face. */}
          <Card
            title="Evidence"
            subtitle="What the exception rests on. Quoted text is what someone outside the business wrote, and is treated as untrusted."
            flush
          >
            {data.evidence.length === 0 ? (
              <EmptyState compact title="No evidence recorded" />
            ) : (
              <ol className="divide-y divide-ink-100">
                {data.evidence.map((item) => (
                  <EvidenceItem key={item.id} item={item} />
                ))}
              </ol>
            )}
          </Card>

          {latest ? (
            <InvestigationPanel investigation={latest} />
          ) : (
            <Card title="Investigation" subtitle="Not run yet.">
              <EmptyState
                compact
                icon={<IconModel />}
                title="No investigation yet"
                description="An investigation reads the records behind this exception with read-only tools and writes up the likely cause and the options. It cannot change anything."
                action={
                  <Button variant="primary" onClick={() => investigate.run()} loading={investigate.pending}>
                    Investigate
                  </Button>
                }
              />
            </Card>
          )}

          <Card title="History" subtitle="Everything done about this exception, and by whom." flush>
            {history.loading && !history.data ? (
              <Loading rows={3} />
            ) : !history.data || history.data.length === 0 ? (
              <EmptyState compact title="No history recorded" />
            ) : (
              <div className="px-4 py-4">
                <Timeline
                  items={history.data.map((event) => ({
                    key: event.id,
                    at: dateTime(event.occurred_at),
                    title: event.summary,
                    tone:
                      event.action.includes("approved") || event.action.includes("executed")
                        ? "ok"
                        : event.action.includes("rejected") || event.action.includes("failed")
                          ? "bad"
                          : event.actor_type === "ai"
                            ? "info"
                            : "neutral",
                    detail: actorName(event),
                  }))}
                />
              </div>
            )}
          </Card>
        </div>

        <aside className="space-y-6">
          <Card
            title={
              <span className="flex items-center gap-2">
                Proposed actions
                {pending.length > 0 && (
                  <span className="rounded bg-brand-600 px-1.5 text-2xs font-semibold text-white tnum">
                    {pending.length} waiting
                  </span>
                )}
              </span>
            }
            subtitle="Nothing is sent or changed until a person approves it."
            flush
          >
            {proposals.loading && !proposals.data ? (
              <Loading rows={2} />
            ) : !proposals.data || proposals.data.length === 0 ? (
              <p className="px-4 py-3.5 text-[13px] leading-5 text-ink-600">
                {!data.investigated_at
                  ? "Nothing proposed yet. Run an investigation, or decide yourself and resolve the exception."
                  : discarded.length > 0
                    ? // Report what actually happened: the investigation may
                      // well have recommended something the gate then refused.
                      `The investigation recommended ${discarded.length === 1 ? "an action" : `${discarded.length} actions`} that ${discarded.length === 1 ? "was" : "were"} refused before reaching you: ${discarded
                        .map((d) => `${actionTypeLabel(d.action_type)} — ${DISCARD_REASON[d.reason] ?? humanise(d.reason)}`)
                        .join("; ")}.`
                    : "The investigation did not recommend an action. Review its options and decide."}
              </p>
            ) : (
              <ul className="divide-y divide-ink-100">
                {proposals.data.map((proposal) => (
                  <li key={proposal.id}>
                    <Link href={`/proposals/${proposal.id}`} className="block px-4 py-3 hover:bg-ink-25">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium text-brand-700">{actionTypeLabel(proposal.action_type)}</span>
                        <StatusPill value={proposal.status} />
                      </div>
                      <p className="mt-1 text-[13px] font-medium leading-5 text-ink-900">{proposal.title}</p>
                      <p className="mt-0.5 text-xs text-ink-500">
                        {proposal.origin === "human" ? "Raised by a person" : proposal.origin === "ai_investigation" ? "From the investigation" : "From the rule engine"}{" "}
                        · {ago(proposal.created_at)}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {links.length > 0 && (
            <Card title="Linked records" flush>
              <ul className="divide-y divide-ink-100">
                {links.map((link) => (
                  <li key={link.key}>
                    <Link
                      href={link.href(String(data[link.key]))}
                      className="flex items-center justify-between px-4 py-2.5 text-[13px] text-ink-800 hover:bg-ink-25 hover:text-brand-700"
                    >
                      {link.label}
                      <IconArrowRight size={13} className="text-ink-400" />
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Timing">
            <dl className="space-y-2 text-[13px]">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">First detected</dt>
                <dd className="text-ink-900">{dateTime(data.first_detected_at)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Last checked</dt>
                <dd className="text-ink-900">{dateTime(data.last_evaluated_at)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Closed</dt>
                <dd className="text-ink-900">{data.resolved_at ? dateTime(data.resolved_at) : "Still open"}</dd>
              </div>
            </dl>
            {data.resolution_note && (
              <p className="mt-3 rounded-md bg-ink-50 px-2.5 py-2 text-[13px] text-ink-700">{data.resolution_note}</p>
            )}
          </Card>
        </aside>
      </div>

      <ConfirmDialog
        open={closing !== null}
        title={closing === "resolved" ? "Mark this exception resolved" : "Dismiss this exception"}
        pending={close.pending}
        confirmLabel={closing === "resolved" ? "Mark resolved" : "Dismiss"}
        tone={closing === "dismissed" ? "danger" : "default"}
        onCancel={() => setClosing(null)}
        onConfirm={() => closing && close.run(closing, note)}
        body={
          <div className="space-y-2">
            <p>
              {closing === "resolved"
                ? "Say what was done, so the next person reading this knows."
                : "Dismissing says this does not need acting on. Say why — it stays on the record."}
            </p>
            <label htmlFor="close-note" className="sr-only">
              Note
            </label>
            <textarea
              id="close-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              className={textareaClass}
              placeholder="e.g. Supplier confirmed dispatch this morning; material arrives Tuesday."
            />
            {close.error && <p className="text-[13px] text-critical-text">{close.error.message}</p>}
          </div>
        }
      />
    </>
  );
}

"use client";

import { dateTime } from "@/lib/format";
import { actionTypeLabel } from "@/lib/labels";
import type { Investigation } from "@/lib/types";
import { IconModel } from "./icons";
import { Badge, Disclosure, ProvenanceTag } from "./ui";

/**
 * An investigation, presented as what it is: an interpretation.
 *
 * It sits in its own violet-edged panel, is labelled on its face, and never
 * borrows the styling of the calculated impact above it. The operational
 * facts stay primary; this explains them. When no model was involved (the
 * deterministic stand-in), it says so — rule-based text dressed as AI output
 * would be the same kind of lie as the reverse.
 */
export function InvestigationPanel({ investigation }: { investigation: Investigation }) {
  const findings = investigation.findings;
  const stubbed = investigation.is_stubbed || findings?.stubbed;
  const tools = investigation.tool_calls ?? [];

  return (
    <section
      aria-labelledby={`investigation-${investigation.id}`}
      className="overflow-hidden rounded-lg border border-ai-border bg-white shadow-card"
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-ai-border bg-ai-bg/60 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <IconModel size={16} className="text-ai-text" />
          <h2 id={`investigation-${investigation.id}`} className="text-[13.5px] font-semibold text-ink-950">
            {stubbed ? "Investigation" : "AI investigation"}
          </h2>
          {stubbed ? (
            <ProvenanceTag kind="fact" label="Rule-based · no model" />
          ) : (
            <ProvenanceTag kind="ai" />
          )}
        </div>
        <p className="text-xs text-ink-500">
          {dateTime(investigation.completed_at ?? investigation.started_at)}
          {investigation.model && !stubbed ? ` · ${investigation.model}` : ""}
        </p>
      </header>

      {!findings ? (
        <p className="px-4 py-4 text-[13px] text-ink-600">
          {investigation.error ?? "This investigation produced no findings."}
        </p>
      ) : (
        <div className="space-y-4 px-4 py-4">
          {stubbed && (
            <p className="text-xs leading-5 text-ink-500">
              No model is configured, so this was written by TextileOps&apos; deterministic rules. It
              restates the recorded evidence and does not reason beyond it.
            </p>
          )}

          <Block title="Summary">
            <p className="max-w-prose text-[13.5px] leading-6 text-ink-800">{findings.what_happened}</p>
          </Block>

          <Block
            title="Likely cause"
            aside={
              <Badge
                tone={findings.root_cause.kind === "established" ? "ok" : "warn"}
                title={
                  findings.root_cause.kind === "established"
                    ? "Every supporting fact came from a read-only tool result."
                    : "Inferred. Not every supporting fact was confirmed from records."
                }
              >
                {findings.root_cause.kind === "established" ? "Established from records" : "Hypothesis"}
              </Badge>
            }
          >
            <p className="max-w-prose text-[13.5px] leading-6 text-ink-800">{findings.root_cause.statement}</p>
          </Block>

          {findings.evidence.length > 0 && (
            <Block title="Evidence considered">
              <ul className="space-y-1.5">
                {findings.evidence.map((item, index) => (
                  <li key={index} className="flex gap-2 text-[13px] leading-5">
                    <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-400" />
                    <span className="min-w-0">
                      <span className="font-medium text-ink-900">{item.label}</span>
                      <span className="text-ink-600"> — {item.detail}</span>
                      <span className="ml-1 font-mono text-2xs text-ink-400">{item.source}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Block>
          )}

          {findings.missing_information.length > 0 && (
            <Block title="Uncertain or missing">
              <ul className="space-y-1">
                {findings.missing_information.map((item, index) => (
                  <li key={index} className="flex gap-2 text-[13px] leading-5 text-ink-700">
                    <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-medium-solid" />
                    {item}
                  </li>
                ))}
              </ul>
            </Block>
          )}

          {findings.recommended_action && (
            <Block title="Suggested action">
              <div className="rounded-md border border-ink-150 bg-ink-25 px-3 py-2.5">
                <p className="text-xs font-medium text-brand-700">
                  {actionTypeLabel(findings.recommended_action.action_type)}
                </p>
                <p className="mt-0.5 text-[13.5px] font-medium text-ink-900">{findings.recommended_action.title}</p>
                <p className="mt-1 max-w-prose text-[13px] leading-5 text-ink-600">
                  {findings.recommended_action.rationale}
                </p>
              </div>
              <p className="mt-1.5 text-xs text-ink-500">
                A suggestion only. It becomes a proposal only if it passes the deterministic checks,
                and does nothing until a person approves it.
              </p>
            </Block>
          )}

          {(findings.options.length > 0 || findings.operational_impact || findings.financial_impact) && (
            <Disclosure summary={`Options and trade-offs${findings.options.length ? ` (${findings.options.length})` : ""}`}>
              <div className="space-y-3">
                {findings.operational_impact && (
                  <p className="max-w-prose text-[13px] text-ink-700">
                    <span className="font-medium text-ink-900">Operational: </span>
                    {findings.operational_impact}
                  </p>
                )}
                {findings.financial_impact && (
                  <p className="max-w-prose text-[13px] text-ink-700">
                    <span className="font-medium text-ink-900">Financial: </span>
                    {findings.financial_impact}
                  </p>
                )}
                {findings.options.map((option) => (
                  <div key={option.title} className="rounded-md border border-ink-150 px-3 py-2">
                    <p className="text-[13px] font-medium text-ink-900">{option.title}</p>
                    <p className="mt-0.5 text-[13px] text-ink-700">{option.description}</p>
                    <p className="mt-1 text-xs text-ink-500">Trade-off: {option.trade_off}</p>
                  </div>
                ))}
              </div>
            </Disclosure>
          )}

          <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-ink-100 pt-2.5 text-xs text-ink-500">
            <span>
              {tools.length} read-only {tools.length === 1 ? "lookup" : "lookups"}
              {tools.length > 0 && (
                <span className="text-ink-400"> ({Array.from(new Set(tools.map((t) => t.name))).join(", ")})</span>
              )}
            </span>
            <span>Stated confidence {Math.round(findings.confidence * 100)}%</span>
            <span className="text-ink-400">It could read records; it could not change any.</span>
          </footer>
        </div>
      )}
    </section>
  );
}

function Block({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <h3 className="text-2xs font-semibold uppercase tracking-wider text-ink-500">{title}</h3>
        {aside}
      </div>
      {children}
    </div>
  );
}

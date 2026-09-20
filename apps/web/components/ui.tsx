"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { humanise } from "@/lib/format";

/* ---------------------------------------------------------------- surfaces */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-ink-200 bg-white shadow-sm ${className}`}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: { label: string; href: string }[];
}) {
  return (
    <header className="mb-5">
      {breadcrumb && breadcrumb.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-1.5 text-xs text-ink-500">
          {breadcrumb.map((crumb, index) => (
            <span key={crumb.href}>
              {index > 0 && <span className="px-1.5 text-ink-300">/</span>}
              <Link href={crumb.href} className="hover:text-ink-800 hover:underline">
                {crumb.label}
              </Link>
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink-950">{title}</h1>
          {description && <p className="mt-1 text-sm text-ink-600">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ states */

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 px-4 py-10 text-sm text-ink-500"
    >
      <span className="h-3 w-3 animate-pulse rounded-full bg-ink-300" aria-hidden />
      {label}…
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-sm font-medium text-ink-800">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-md text-sm text-ink-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-critical-border bg-critical-bg px-4 py-3">
      <p className="text-sm font-medium text-critical-text">Something went wrong</p>
      <p className="mt-1 text-sm text-critical-text/80">{error.message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded border border-critical-border bg-white px-2.5 py-1 text-xs font-medium text-critical-text hover:bg-critical-bg"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ badges */

const SEVERITY_CLASS: Record<string, string> = {
  critical: "bg-critical-bg text-critical-text border-critical-border",
  high: "bg-high-bg text-high-text border-high-border",
  medium: "bg-medium-bg text-medium-text border-medium-border",
  low: "bg-low-bg text-low-text border-low-border",
};

const RISK_CLASS: Record<string, string> = {
  on_track: "bg-good-bg text-good-text border-good-border",
  watch: "bg-medium-bg text-medium-text border-medium-border",
  at_risk: "bg-high-bg text-high-text border-high-border",
  late: "bg-critical-bg text-critical-text border-critical-border",
};

const STATUS_CLASS: Record<string, string> = {
  ok: "bg-good-bg text-good-text border-good-border",
  warn: "bg-medium-bg text-medium-text border-medium-border",
  bad: "bg-critical-bg text-critical-text border-critical-border",
  neutral: "bg-ink-50 text-ink-700 border-ink-200",
};

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: keyof typeof STATUS_CLASS;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${STATUS_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${
        SEVERITY_CLASS[severity] ?? STATUS_CLASS.neutral
      }`}
    >
      {severity}
    </span>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const labels: Record<string, string> = {
    on_track: "On track",
    watch: "Watch",
    at_risk: "At risk",
    late: "Late",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${
        RISK_CLASS[risk] ?? STATUS_CLASS.neutral
      }`}
    >
      {labels[risk] ?? humanise(risk)}
    </span>
  );
}

/**
 * Colour is a claim. A grey pill reads as "nothing to see here", so any status
 * missing from this map is silently reassuring — which is how a QC *reject*
 * came to render in the same neutral grey as *not applicable*. Every status
 * string the API can emit must appear here; `statusTone.test.ts` checks the
 * list against the backend enums so a new status cannot be added upstream and
 * quietly inherit the reassuring default.
 */
export const READINESS_TONE: Record<string, keyof typeof STATUS_CLASS> = {
  // Material coverage
  ready: "ok",
  partial: "warn",
  short: "bad",
  not_applicable: "neutral",
  materials_not_covered: "bad",
  nothing_planned: "warn",

  // Quality. "pass" and "reject" are the raw QCOutcome values; "passed" and
  // "rejected" are the order-level roll-ups. Both reach this map.
  pass: "ok",
  passed: "ok",
  conditional_pass: "warn",
  rework: "warn",
  reject: "bad",
  rejected: "bad",
  pending: "warn",
  not_inspected: "neutral",
  partially_inspected: "warn",

  // Production
  planned: "neutral",
  scheduled: "neutral",
  not_started: "neutral",
  in_progress: "neutral",
  blocked: "bad",
  completed: "ok",
  partially_cancelled: "warn",
  cancelled: "neutral",

  // Sales orders
  draft: "neutral",
  confirmed: "neutral",
  in_production: "neutral",
  ready_to_ship: "ok",
  closed: "ok",

  // Shipping
  nothing_to_ship: "neutral",
  not_shipped: "warn",
  packed: "neutral",
  dispatched: "neutral",
  in_transit: "neutral",
  partially_shipped: "warn",
  shipped: "ok",
  delivered: "ok",
  delayed: "bad",

  // Purchase orders
  sent: "neutral",
  acknowledged: "neutral",
  partially_received: "warn",
  received: "ok",

  // Stock lots. Quarantined cloth is real and countable but cannot be sold,
  // so it is a warning, not a success.
  available: "ok",
  quarantine: "warn",
  consumed: "neutral",

  // Documents and ingestion
  queued: "neutral",
  processing: "neutral",
  extracted: "ok",
  needs_review: "warn",
  applied: "ok",
  failed: "bad",

  // Exceptions. "dismissed" is a human judgement that the exception did not
  // matter, not a success — green would claim the problem was fixed.
  open: "warn",
  investigating: "warn",
  action_proposed: "warn",
  resolved: "ok",
  dismissed: "neutral",

  // Proposals, approvals and executions
  pending_approval: "warn",
  approved: "ok",
  executed: "ok",
  awaiting_external: "warn",
  expired: "neutral",
  succeeded: "ok",
  superseded: "neutral",
};

export function StatusPill({ value }: { value: string }) {
  return <Badge tone={READINESS_TONE[value] ?? "neutral"}>{humanise(value)}</Badge>;
}

/* ------------------------------------------------------------------ tables */

export function Table({
  head,
  children,
  caption,
}: {
  head: ReactNode[];
  children: ReactNode;
  caption?: string;
}) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="min-w-full border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-ink-200 text-left">
            {head.map((cell, index) => (
              <th
                key={index}
                scope="col"
                className="whitespace-nowrap px-2 py-2 text-xs font-semibold uppercase tracking-wide text-ink-500"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({
  children,
  className = "",
  numeric = false,
  title,
  colSpan,
}: {
  children: ReactNode;
  className?: string;
  numeric?: boolean;
  title?: string;
  colSpan?: number;
}) {
  return (
    <td
      title={title}
      colSpan={colSpan}
      className={`px-2 py-2 align-top text-ink-800 ${
        numeric ? "whitespace-nowrap text-right tabular-nums" : ""
      } ${className}`}
    >
      {children}
    </td>
  );
}

/* ----------------------------------------------------------------- inputs */

export function Button({
  children,
  onClick,
  type = "button",
  variant = "secondary",
  disabled = false,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  title?: string;
}) {
  const styles: Record<string, string> = {
    primary: "bg-ink-900 text-white hover:bg-ink-800 disabled:bg-ink-300",
    secondary:
      "border border-ink-300 bg-white text-ink-800 hover:bg-ink-50 disabled:text-ink-400",
    danger:
      "border border-critical-border bg-white text-critical-text hover:bg-critical-bg disabled:opacity-50",
    ghost: "text-ink-600 hover:bg-ink-50 hover:text-ink-900",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-700">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded border border-ink-300 bg-white px-2.5 py-1.5 text-sm text-ink-900 " +
  "placeholder:text-ink-400 focus:border-ink-500 focus:outline-none focus:ring-1 focus:ring-ink-500";

export function Select({
  value,
  onChange,
  options,
  label,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  label: string;
  id: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/* ------------------------------------------------------------------- misc */

export function DefinitionList({
  items,
}: {
  items: { term: string; value: ReactNode; hint?: string }[];
}) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div key={item.term}>
          <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">
            {item.term}
          </dt>
          <dd className="mt-0.5 text-sm text-ink-900">{item.value}</dd>
          {item.hint && <dd className="text-xs text-ink-500">{item.hint}</dd>}
        </div>
      ))}
    </dl>
  );
}

export function Unavailable({ reason }: { reason?: string | null }) {
  return (
    <span className="text-ink-500" title={reason ?? undefined}>
      Not available
      {reason ? <span className="sr-only"> — {reason}</span> : null}
    </span>
  );
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
  pending = false,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  pending?: boolean;
}) {
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/30 p-4"
    >
      <div className="w-full max-w-md rounded-lg border border-ink-200 bg-white p-4 shadow-lg">
        <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
        <div className="mt-2 text-sm text-ink-700">{body}</div>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm} disabled={pending}>
            {pending ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

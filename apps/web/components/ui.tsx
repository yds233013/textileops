"use client";

/**
 * TextileOps component library.
 *
 * Every page is built from these; a page that reaches for its own border,
 * shadow or badge colour is a page that will drift. Three rules run through
 * all of it:
 *
 * 1. **Colour is a claim.** A tone says something about the world. Grey means
 *    "nothing to report", so nothing that needs attention is ever grey.
 * 2. **Unknown is not zero.** An unavailable figure says it is unavailable.
 * 3. **Provenance is visible.** What the system calculated, what a third party
 *    wrote and what a model thinks are styled differently, always.
 */

import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { humanise } from "@/lib/format";
import { statusLabel } from "@/lib/labels";
import { IconAlert, IconCalculator, IconInfo, IconModel, IconQuote, IconX } from "./icons";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/* ================================================================ surfaces */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  flush = false,
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** No inner padding — for tables and lists that run edge to edge. */
  flush?: boolean;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={cx("rounded-lg border border-ink-150 bg-white shadow-card", className)}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-ink-100 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-[13.5px] font-semibold text-ink-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={flush ? "" : "px-4 py-3.5"}>{children}</div>
    </section>
  );
}

/** A titled region of a page without a box around it. */
export function Section({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      <div className="mb-2.5 flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
          {description && <p className="mt-0.5 text-xs text-ink-500">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  meta,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: { label: string; href: string }[];
  /** Badges and facts under the title: status, severity, reference. */
  meta?: ReactNode;
  eyebrow?: ReactNode;
}) {
  const plain = typeof title === "string" ? title : null;
  useEffect(() => {
    if (plain) document.title = `${plain} · TextileOps`;
  }, [plain]);
  return (
    <header className="mb-6">
      {breadcrumb && breadcrumb.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-1.5 text-xs text-ink-500">
          {breadcrumb.map((crumb, index) => (
            <span key={crumb.href} className="flex items-center gap-1.5">
              {index > 0 && <span className="text-ink-300">/</span>}
              <Link href={crumb.href} className="hover:text-ink-900 hover:underline">
                {crumb.label}
              </Link>
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          {eyebrow && <div className="mb-1 text-xs font-medium text-ink-500">{eyebrow}</div>}
          <h1 className="text-[22px] font-semibold leading-7 tracking-[-0.01em] text-ink-950">
            {title}
          </h1>
          {description && (
            <p className="mt-1 max-w-prose text-[13.5px] text-ink-600">{description}</p>
          )}
          {meta && <div className="mt-2.5 flex flex-wrap items-center gap-2">{meta}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/* ================================================================== states */

export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden className={cx("skeleton block h-3.5", className)} />;
}

/**
 * Loading placeholder shaped like what is coming. A spinner on a blank page
 * reads as broken after a second; rows of the right shape read as "nearly".
 */
export function Loading({
  label = "Loading",
  variant = "rows",
  rows = 6,
}: {
  label?: string;
  variant?: "rows" | "cards" | "page";
  rows?: number;
}) {
  return (
    <div role="status" aria-live="polite" className="w-full">
      <span className="sr-only">{label}…</span>
      {variant === "cards" && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-ink-150 bg-white p-4 shadow-card">
              <Skeleton className="w-24" />
              <Skeleton className="mt-3 h-6 w-16" />
            </div>
          ))}
        </div>
      )}
      {variant === "page" && (
        <div className="space-y-4">
          <Skeleton className="h-6 w-72" />
          <Skeleton className="w-96" />
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-48" />
        </div>
      )}
      {variant === "rows" && (
        <div className="divide-y divide-ink-100">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-3">
              <Skeleton className="w-20" />
              <Skeleton className="w-40" />
              <Skeleton className="ml-auto w-24" />
              <Skeleton className="w-16" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
  compact = false,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cx("px-4 text-center", compact ? "py-6" : "py-12")}>
      {icon && (
        <div className="mx-auto mb-3 flex h-9 w-9 items-center justify-center rounded-full bg-ink-100 text-ink-500">
          {icon}
        </div>
      )}
      <p className="text-[13.5px] font-medium text-ink-800">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-sm text-[13px] text-ink-500">{description}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex gap-3 rounded-lg border border-critical-border bg-critical-bg px-4 py-3">
      <IconAlert className="mt-0.5 shrink-0 text-critical-solid" />
      <div className="min-w-0">
        <p className="text-[13.5px] font-medium text-critical-text">Something went wrong</p>
        <p className="mt-0.5 text-[13px] text-critical-text/80">{error.message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded-md border border-critical-border bg-white px-2.5 py-1 text-xs font-medium text-critical-text hover:bg-critical-bg"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Alert({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "info" | "warn" | "bad" | "ok";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const styles = {
    info: "border-info-border bg-info-bg text-info-text",
    warn: "border-medium-border bg-medium-bg text-medium-text",
    bad: "border-critical-border bg-critical-bg text-critical-text",
    ok: "border-good-border bg-good-bg text-good-text",
  }[tone];
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cx("flex items-start gap-3 rounded-lg border px-3.5 py-2.5", styles)}>
      {tone === "bad" || tone === "warn" ? (
        <IconAlert className="mt-0.5 shrink-0" />
      ) : (
        <IconInfo className="mt-0.5 shrink-0" />
      )}
      <div className="min-w-0 flex-1 text-[13px]">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? "mt-0.5 opacity-90" : ""}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/* ================================================================== badges */

const TONE_CLASS = {
  ok: "bg-good-bg text-good-text ring-good-border",
  warn: "bg-medium-bg text-medium-text ring-medium-border",
  bad: "bg-critical-bg text-critical-text ring-critical-border",
  info: "bg-info-bg text-info-text ring-info-border",
  neutral: "bg-ink-50 text-ink-700 ring-ink-200",
} as const;

const DOT_CLASS = {
  ok: "bg-good-solid",
  warn: "bg-medium-solid",
  bad: "bg-critical-solid",
  info: "bg-info-solid",
  neutral: "bg-ink-400",
} as const;

export type Tone = keyof typeof TONE_CLASS;

export function Badge({
  children,
  tone = "neutral",
  title,
  dot = false,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
  dot?: boolean;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 py-[1px] text-xs font-medium ring-1 ring-inset",
        TONE_CLASS[tone],
      )}
    >
      {dot && <span aria-hidden className={cx("h-1.5 w-1.5 rounded-full", DOT_CLASS[tone])} />}
      {children}
    </span>
  );
}

const SEVERITY_STYLE: Record<string, { cls: string; dot: string; label: string }> = {
  critical: { cls: "bg-critical-solid text-white ring-critical-solid", dot: "", label: "Critical" },
  high: { cls: "bg-high-bg text-high-text ring-high-border", dot: "bg-high-solid", label: "High" },
  medium: { cls: "bg-medium-bg text-medium-text ring-medium-border", dot: "bg-medium-solid", label: "Medium" },
  low: { cls: "bg-low-bg text-low-text ring-low-border", dot: "bg-low-solid", label: "Low" },
};

export function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLE[severity];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 py-[1px] text-xs font-semibold ring-1 ring-inset",
        style?.cls ?? TONE_CLASS.neutral,
      )}
    >
      {style?.dot && <span aria-hidden className={cx("h-1.5 w-1.5 rounded-full", style.dot)} />}
      {style?.label ?? humanise(severity)}
    </span>
  );
}

/** A coloured bar for the left edge of a row or card, keyed by severity. */
export const SEVERITY_EDGE: Record<string, string> = {
  critical: "bg-critical-solid",
  high: "bg-high-solid",
  medium: "bg-medium-solid",
  low: "bg-low-solid",
};

const RISK_STYLE: Record<string, { tone: Tone; label: string }> = {
  on_track: { tone: "ok", label: "On track" },
  watch: { tone: "warn", label: "Watch" },
  at_risk: { tone: "bad", label: "At risk" },
  late: { tone: "bad", label: "Late" },
};

export function RiskBadge({ risk }: { risk: string }) {
  const style = RISK_STYLE[risk];
  if (risk === "late") {
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-critical-solid px-1.5 py-[1px] text-xs font-semibold text-white">
        Late
      </span>
    );
  }
  return (
    <Badge tone={style?.tone ?? "neutral"} dot>
      {style?.label ?? humanise(risk)}
    </Badge>
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
export const READINESS_TONE: Record<string, Tone> = {
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
  in_progress: "info",
  blocked: "bad",
  completed: "ok",
  partially_cancelled: "warn",
  cancelled: "neutral",

  // Sales orders
  draft: "neutral",
  confirmed: "neutral",
  in_production: "info",
  ready_to_ship: "ok",
  closed: "ok",

  // Shipping. Dispatch is not arrival: in transit is information, only
  // delivered is good news.
  nothing_to_ship: "neutral",
  not_shipped: "warn",
  packed: "neutral",
  dispatched: "info",
  in_transit: "info",
  partially_shipped: "warn",
  shipped: "info",
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
  processing: "info",
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

export function StatusPill({ value, dot = true }: { value: string; dot?: boolean }) {
  return (
    <Badge tone={READINESS_TONE[value] ?? "neutral"} dot={dot}>
      {statusLabel(value)}
    </Badge>
  );
}

/* ============================================================== provenance */

const PROVENANCE = {
  fact: {
    label: "Calculated",
    title: "Worked out by TextileOps from its own records. Deterministic, not a model.",
    cls: "bg-fact-bg text-fact-text ring-fact-border",
    Icon: IconCalculator,
  },
  source: {
    label: "Quoted source",
    title: "Written by a third party — a supplier, a customer, a document. Treated as untrusted data.",
    cls: "bg-source-bg text-source-text ring-source-border",
    Icon: IconQuote,
  },
  ai: {
    label: "AI interpretation",
    title: "Written by a model. An opinion to weigh, never a record, and it cannot change anything.",
    cls: "bg-ai-bg text-ai-text ring-ai-border",
    Icon: IconModel,
  },
} as const;

/** Where a piece of information came from. Shown wherever the answer is not obvious. */
export function ProvenanceTag({
  kind,
  label,
}: {
  kind: keyof typeof PROVENANCE;
  label?: string;
}) {
  const p = PROVENANCE[kind];
  return (
    <span
      title={p.title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-[1px] text-2xs font-semibold uppercase tracking-wide ring-1 ring-inset",
        p.cls,
      )}
    >
      <p.Icon size={12} />
      {label ?? p.label}
    </span>
  );
}

/* ================================================================== metrics */

/**
 * One number and what it means. A figure without its unit or its caveat is a
 * figure someone will misread, so both are first-class.
 */
export function Stat({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
  href,
  size = "md",
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: string | null;
  hint?: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad";
  href?: string;
  size?: "sm" | "md";
}) {
  const valueTone = {
    neutral: "text-ink-950",
    good: "text-good-text",
    warn: "text-high-text",
    bad: "text-critical-text",
  }[tone];
  const body = (
    <>
      <div className="text-xs font-medium text-ink-500">{label}</div>
      <div className={cx("mt-1 flex items-baseline gap-1 font-semibold tnum", valueTone, size === "md" ? "text-2xl leading-8" : "text-lg leading-6")}>
        {value}
        {unit && <span className="text-sm font-medium text-ink-500">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 text-xs text-ink-500">{hint}</div>}
    </>
  );
  return href ? (
    <Link href={href} className="block rounded-md transition hover:bg-ink-50/80">
      {body}
    </Link>
  ) : (
    <div>{body}</div>
  );
}

/** A row of stats inside one card, separated by hairlines. */
export function StatStrip({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 divide-ink-100 overflow-hidden rounded-lg border border-ink-150 bg-white shadow-card sm:grid-cols-3 lg:auto-cols-fr lg:grid-flow-col lg:grid-cols-none lg:divide-x [&>*]:px-4 [&>*]:py-3.5">
      {children}
    </div>
  );
}

/* =================================================================== tables */

export function Table({
  head,
  children,
  caption,
  align,
  className = "",
}: {
  head: ReactNode[];
  children: ReactNode;
  caption?: string;
  /** Per-column alignment; numeric columns should be "right". */
  align?: ("left" | "right" | "center")[];
  className?: string;
}) {
  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="min-w-full border-collapse text-[13px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-ink-150 bg-ink-25">
            {head.map((cell, index) => (
              <th
                key={index}
                scope="col"
                className={cx(
                  "whitespace-nowrap px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-ink-500 first:pl-4 last:pr-4",
                  align?.[index] === "right" ? "text-right" : align?.[index] === "center" ? "text-center" : "text-left",
                )}
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
  nowrap = false,
}: {
  children: ReactNode;
  className?: string;
  numeric?: boolean;
  title?: string;
  colSpan?: number;
  nowrap?: boolean;
}) {
  return (
    <td
      title={title}
      colSpan={colSpan}
      className={cx(
        "px-3 py-2.5 align-top text-ink-800 first:pl-4 last:pr-4",
        numeric && "whitespace-nowrap text-right tnum",
        nowrap && "whitespace-nowrap",
        className,
      )}
    >
      {children}
    </td>
  );
}

/** A table row that is also a link, without nesting anchors inside cells. */
export function RowLink({
  href,
  children,
  className = "",
  edge,
}: {
  href: string;
  children: ReactNode;
  className?: string;
  /** Tailwind background class for a severity edge on the first cell. */
  edge?: string;
}) {
  return (
    <tr
      className={cx("group cursor-pointer transition-colors hover:bg-brand-50/40", edge && "[&>td:first-child]:relative", className)}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest("a,button,input,select,label")) return;
        if (event.metaKey || event.ctrlKey) {
          window.open(href, "_blank");
        } else {
          window.location.assign(href);
        }
      }}
    >
      {children}
    </tr>
  );
}

/* =================================================================== inputs */

export function Button({
  children,
  onClick,
  type = "button",
  variant = "secondary",
  size = "md",
  disabled = false,
  title,
  href,
  icon,
  loading = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "secondary" | "danger" | "ghost" | "danger-solid";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  title?: string;
  href?: string;
  icon?: ReactNode;
  loading?: boolean;
}) {
  const styles: Record<string, string> = {
    primary:
      "bg-brand-700 text-white shadow-sm hover:bg-brand-800 disabled:bg-ink-300 disabled:shadow-none",
    secondary:
      "bg-white text-ink-800 shadow-sm ring-1 ring-inset ring-ink-200 hover:bg-ink-50 disabled:text-ink-400",
    danger:
      "bg-white text-critical-text shadow-sm ring-1 ring-inset ring-critical-border hover:bg-critical-bg disabled:opacity-50",
    "danger-solid": "bg-critical-solid text-white shadow-sm hover:bg-red-700 disabled:opacity-50",
    ghost: "text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:text-ink-300",
  };
  const sizes = {
    sm: "h-7 px-2 text-xs gap-1",
    md: "h-8 px-3 text-[13px] gap-1.5",
    lg: "h-10 px-4 text-sm gap-2",
  };
  const className = cx(
    "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium transition disabled:cursor-not-allowed",
    styles[variant],
    sizes[size],
  );
  const content = (
    <>
      {loading ? (
        <span aria-hidden className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />
      ) : (
        icon
      )}
      {children}
    </>
  );
  if (href && !disabled) {
    return (
      <Link href={href} className={className} title={title}>
        {content}
      </Link>
    );
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled || loading} title={title} className={className}>
      {content}
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
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-700">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "block h-8 w-full rounded-md border-0 bg-white px-2.5 text-[13px] text-ink-900 shadow-sm ring-1 ring-inset ring-ink-200 " +
  "placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-ink-50";

export const textareaClass = inputClass.replace("h-8", "min-h-[96px]") + " py-2 leading-5";

export function Select({
  value,
  onChange,
  options,
  label,
  id,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  label: string;
  id: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cx(inputClass, "pr-8")}
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

/** A row of filters above a table. */
export function FilterBar({ children, summary }: { children: ReactNode; summary?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 border-b border-ink-100 px-4 py-2.5">
      {children}
      {summary && <div className="ml-auto text-xs text-ink-500">{summary}</div>}
    </div>
  );
}

/** Segmented filter: a handful of mutually exclusive choices, each with a count. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string; count?: number }[];
  label: string;
}) {
  return (
    // Scrolls sideways on a narrow screen rather than pushing the page wider.
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-md bg-ink-100 p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cx(
              "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded px-2.5 text-xs font-medium transition",
              active ? "bg-white text-ink-900 shadow-sm" : "text-ink-600 hover:text-ink-900",
            )}
          >
            {option.label}
            {option.count !== undefined && (
              <span className={cx("tnum", active ? "text-ink-500" : "text-ink-400")}>{option.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  tabs: { value: T; label: string; count?: number }[];
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex max-w-full gap-4 overflow-x-auto border-b border-ink-150">
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cx(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-0.5 pb-2 pt-1 text-[13px] font-medium transition",
              active ? "border-brand-600 text-ink-950" : "border-transparent text-ink-500 hover:text-ink-800",
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="rounded bg-ink-100 px-1.5 text-2xs font-semibold text-ink-600 tnum">{tab.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ===================================================================== misc */

export function DefinitionList({
  items,
  columns = 3,
}: {
  items: { term: string; value: ReactNode; hint?: ReactNode }[];
  columns?: 2 | 3 | 4;
}) {
  const grid = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-2 lg:grid-cols-3", 4: "sm:grid-cols-2 lg:grid-cols-4" }[columns];
  return (
    <dl className={cx("grid grid-cols-1 gap-x-6 gap-y-4", grid)}>
      {items.map((item) => (
        <div key={item.term} className="min-w-0">
          <dt className="text-xs font-medium text-ink-500">{item.term}</dt>
          <dd className="mt-1 text-[13.5px] text-ink-900">{item.value}</dd>
          {item.hint && <dd className="mt-0.5 text-xs text-ink-500">{item.hint}</dd>}
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

/** An inline "(i)" that explains a term on hover or focus. */
export function Hint({ children, label = "What does this mean?" }: { children: ReactNode; label?: string }) {
  const id = useId();
  return (
    <span className="group relative inline-flex align-middle">
      <button type="button" aria-describedby={id} aria-label={label} className="rounded-full text-ink-400 hover:text-ink-700">
        <IconInfo size={13} />
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-40 mb-1.5 w-60 -translate-x-1/2 rounded-md bg-ink-900 px-2.5 py-1.5 text-xs font-normal normal-case leading-4 tracking-normal text-white opacity-0 shadow-raised transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {children}
      </span>
    </span>
  );
}

export interface TimelineItem {
  key: string;
  at: ReactNode;
  title: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
  tag?: ReactNode;
}

/** A vertical sequence of events. Used for orders, POs, batches and audit. */
export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative">
      {items.map((item, index) => (
        <li key={item.key} className="relative flex gap-3 pb-4 last:pb-0">
          {index < items.length - 1 && (
            <span aria-hidden className="absolute left-[5px] top-3.5 h-full w-px bg-ink-150" />
          )}
          <span aria-hidden className={cx("relative mt-1.5 h-[11px] w-[11px] shrink-0 rounded-full border-2 border-white ring-1", item.tone ? `${DOT_CLASS[item.tone]} ring-ink-200` : "bg-ink-300 ring-ink-200")} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[13px] font-medium text-ink-900">{item.title}</span>
              {item.tag}
              <span className="ml-auto whitespace-nowrap text-xs text-ink-500 tnum">{item.at}</span>
            </div>
            {item.detail && <div className="mt-0.5 text-[13px] text-ink-600">{item.detail}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function useDialogKeys(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);
  return ref;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
  pending = false,
  tone = "default",
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  pending?: boolean;
  /** "danger" for anything that cannot be undone. */
  tone?: "default" | "danger";
}) {
  const ref = useDialogKeys(open, pending ? () => {} : onCancel);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/40 p-4 backdrop-blur-[1px]">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md rounded-xl bg-white p-5 shadow-overlay"
      >
        <h2 className="text-[15px] font-semibold text-ink-950">{title}</h2>
        <div className="mt-2 text-[13.5px] leading-5 text-ink-700">{body}</div>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onCancel} disabled={pending}>
            <span data-autofocus>Cancel</span>
          </Button>
          <Button variant={tone === "danger" ? "danger-solid" : "primary"} onClick={onConfirm} disabled={pending} loading={pending}>
            {pending ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** A panel that slides in from the right for detail that should not cost a page load. */
export function Drawer({
  open,
  title,
  onClose,
  children,
  width = "max-w-xl",
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  const ref = useDialogKeys(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-950/30" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "Details"}
        onClick={(event) => event.stopPropagation()}
        className={cx("flex h-full w-full flex-col bg-white shadow-overlay", width)}
      >
        <div className="flex items-center justify-between border-b border-ink-150 px-5 py-3.5">
          <h2 className="text-[15px] font-semibold text-ink-950">{title}</h2>
          <button type="button" data-autofocus onClick={onClose} aria-label="Close" className="rounded-md p-1 text-ink-500 hover:bg-ink-100 hover:text-ink-900">
            <IconX />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

/** Collapsible detail that is useful but not primary. */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-600 hover:text-ink-900"
      >
        <span className={cx("inline-block transition-transform", open && "rotate-90")} aria-hidden>
          ▸
        </span>
        {summary}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

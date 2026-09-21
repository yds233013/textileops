"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AttentionCard } from "@/components/attention";
import { ActorTag } from "@/components/audit";
import { IconArrowRight, IconCheckCircle, IconRefresh } from "@/components/icons";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  RiskBadge,
  Segmented,
  Skeleton,
  Stat,
  StatStrip,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { ago, dateTime, dueText, num, plural, shortDate } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import { actionTypeLabel, exceptionTypeLabel } from "@/lib/labels";
import type {
  AttentionCard as AttentionItem,
  AuditEvent,
  Batch,
  Dashboard,
  MetricTile,
  OrderList,
  Position,
  Proposal,
  Supplier,
} from "@/lib/types";

const QUEUE_LIMIT = 8;

type Filter = "all" | "critical" | "orders" | "supply" | "production";

const FILTER_TYPES: Record<Exclude<Filter, "all" | "critical">, string[]> = {
  orders: ["ORDER_AT_RISK", "ORDER_LATE", "SHIPMENT_DELAY"],
  supply: ["MATERIAL_SHORTAGE", "PO_LATE", "SUPPLIER_DELAY", "QUANTITY_MISMATCH", "INVENTORY_ANOMALY"],
  production: ["PRODUCTION_DELAY", "QC_FAILURE"],
};

function matches(card: AttentionItem, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "critical") return card.severity === "critical";
  return FILTER_TYPES[filter].includes(card.exception_type);
}

function metric(data: Dashboard, key: string): MetricTile | undefined {
  return data.metrics.find((m) => m.key === key);
}

function value(tile: MetricTile | undefined): number {
  return typeof tile?.value === "number" ? tile.value : Number(tile?.value ?? 0);
}

/** One sentence that says how the business is doing, from the numbers only. */
function summarise(data: Dashboard): string {
  const open = value(metric(data, "open_orders"));
  const atRisk = value(metric(data, "orders_at_risk"));
  const late = value(metric(data, "orders_late"));
  const short = value(metric(data, "material_shortages"));
  const approvals = value(metric(data, "pending_approvals"));
  const parts: string[] = [];
  if (open === 0) return "There are no open customer orders.";
  if (atRisk + late === 0) parts.push(`All ${plural(open, "open order")} are on track`);
  else
    parts.push(
      `${atRisk + late} of ${plural(open, "open order")} need${atRisk + late === 1 ? "s" : ""} attention` +
        (late ? ` (${late} already late)` : ""),
    );
  if (short) parts.push(`${plural(short, "material")} ${short === 1 ? "is" : "are"} short`);
  if (approvals) parts.push(`${plural(approvals, "action")} ${approvals === 1 ? "is" : "are"} waiting for your approval`);
  return `${parts.join(". ")}.`;
}

export default function CommandCentrePage() {
  const { data, error, loading, reload } = useApi<Dashboard>("/dashboard");
  const [filter, setFilter] = useState<Filter>("all");
  const [notice, setNotice] = useState<string | null>(null);

  const recompute = useAction(async () => {
    const result = await apiFetch<{ created: number; updated: number; auto_resolved: number; unchanged: number }>(
      "/exceptions/recompute",
      { method: "POST" },
    );
    setNotice(
      `Checked everything again: ${result.created} new, ${result.updated} updated, ` +
        `${result.auto_resolved} resolved on their own, ${result.unchanged} unchanged.`,
    );
    reload();
  });

  const queue = useMemo(() => (data ? data.attention_queue.filter((c) => matches(c, filter)) : []), [data, filter]);

  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  const now = new Date();
  const eyebrow = now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

  return (
    <>
      <PageHeader
        eyebrow={eyebrow}
        title="Command centre"
        description={
          data ? summarise(data) : <Skeleton className="mt-1 h-4 w-96" />
        }
        actions={
          <Button
            size="sm"
            icon={<IconRefresh size={14} />}
            onClick={() => recompute.run()}
            loading={recompute.pending}
            title="Re-run every deterministic check against the current records"
          >
            {recompute.pending ? "Checking…" : "Check again"}
          </Button>
        }
      />

      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}
      {recompute.error && (
        <div className="mb-4">
          <ErrorState error={recompute.error} />
        </div>
      )}

      {/* ---------------------------------------------------------- KPIs */}
      {loading && !data ? (
        <Loading variant="cards" label="Reading the state of the business" />
      ) : data ? (
        <KeyNumbers data={data} />
      ) : null}

      {/* ------------------------------------------------ primary + side */}
      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section aria-labelledby="needs-attention">
          <div className="mb-2.5 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 id="needs-attention" className="text-sm font-semibold text-ink-900">
                Needs attention
              </h2>
              <p className="text-xs text-ink-500">Ranked by severity, how soon it bites, and which customer it reaches.</p>
            </div>
            {data && (
              <Segmented
                label="Filter the attention queue"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: "all", label: "All", count: data.attention_queue.length },
                  { value: "critical", label: "Critical", count: data.attention_queue.filter((c) => matches(c, "critical")).length },
                  { value: "orders", label: "Orders", count: data.attention_queue.filter((c) => matches(c, "orders")).length },
                  { value: "supply", label: "Supply", count: data.attention_queue.filter((c) => matches(c, "supply")).length },
                  { value: "production", label: "Production", count: data.attention_queue.filter((c) => matches(c, "production")).length },
                ]}
              />
            )}
          </div>

          <Card flush>
            {loading && !data ? (
              <Loading rows={5} label="Loading the attention queue" />
            ) : !data ? null : queue.length === 0 ? (
              <EmptyState
                icon={<IconCheckCircle />}
                title={filter === "all" ? "Nothing needs your attention right now" : "Nothing in this category"}
                description={
                  filter === "all"
                    ? "Every open order, purchase order, batch and shipment is within its expected bounds. TextileOps keeps checking."
                    : "Nothing open of this kind. Switch back to All to see the rest of the queue."
                }
              />
            ) : (
              <div className="divide-y divide-ink-100">
                {queue.slice(0, QUEUE_LIMIT).map((card) => (
                  <AttentionCard key={card.exception_id} card={card} />
                ))}
              </div>
            )}
            {data && (queue.length > QUEUE_LIMIT || filter === "all") && (
              <Link
                href="/exceptions"
                className="flex items-center justify-center gap-1.5 border-t border-ink-100 py-2.5 text-[13px] font-medium text-brand-700 hover:bg-ink-25"
              >
                See every open exception <IconArrowRight size={13} />
              </Link>
            )}
          </Card>
          {data && (
            <p className="mt-2 text-xs text-ink-400">
              As of {dateTime(data.as_of)}. {data.ai_mode === "model" ? "" : data.ai_note}
            </p>
          )}
        </section>

        <aside className="space-y-6">
          <Approvals />
          <Upcoming />
          <WhereProblemsAre data={data} />
        </aside>
      </div>

      {/* ------------------------------------------------------ secondary */}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <ProductionPanel />
        <MaterialsPanel />
        <SuppliersPanel />
      </div>

      <div className="mt-6">
        <RecentActivity />
      </div>
    </>
  );
}

function KeyNumbers({ data }: { data: Dashboard }) {
  const open = value(metric(data, "open_orders"));
  const onTime = metric(data, "on_time_pct");
  return (
    <StatStrip>
      <Stat
        label="Orders at risk"
        value={value(metric(data, "orders_at_risk"))}
        hint={`of ${open} open · finishing after the promise`}
        tone={value(metric(data, "orders_at_risk")) ? "warn" : "good"}
        href="/orders?risk=at_risk"
      />
      <Stat
        label="Orders late"
        value={value(metric(data, "orders_late"))}
        hint="Promised date passed, cloth still owed"
        tone={value(metric(data, "orders_late")) ? "bad" : "good"}
        href="/orders?risk=late"
      />
      <Stat
        label="Materials short"
        value={value(metric(data, "material_shortages"))}
        hint="For batches already planned"
        tone={value(metric(data, "material_shortages")) ? "bad" : "good"}
        href="/inventory?short=1"
      />
      <Stat
        label="Purchase orders overdue"
        value={value(metric(data, "late_pos"))}
        hint={`of ${value(metric(data, "open_pos"))} open`}
        tone={value(metric(data, "late_pos")) ? "bad" : "good"}
        href="/purchase-orders?overdue=1"
      />
      <Stat
        label="Awaiting your approval"
        value={value(metric(data, "pending_approvals"))}
        hint="Nothing happens until someone approves"
        tone={value(metric(data, "pending_approvals")) ? "warn" : "neutral"}
        href="/proposals"
      />
      <Stat
        label="On-time delivery"
        value={onTime?.value ?? "—"}
        unit={onTime?.value !== null && onTime?.value !== undefined ? "%" : null}
        hint={onTime?.hint ?? undefined}
        tone={onTime?.tone ?? "neutral"}
      />
    </StatStrip>
  );
}

function PanelLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-900">
      {children} <IconArrowRight size={12} />
    </Link>
  );
}

function Approvals() {
  const { data, loading } = useApi<Proposal[]>("/proposals", { status: "pending_approval" });
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Awaiting your approval
          {data && data.length > 0 && (
            <span className="rounded bg-brand-600 px-1.5 text-2xs font-semibold text-white tnum">{data.length}</span>
          )}
        </span>
      }
      subtitle="Proposed actions. Nothing is sent or changed until a person approves."
      flush
    >
      {loading && !data ? (
        <Loading rows={2} />
      ) : !data || data.length === 0 ? (
        <EmptyState compact title="Nothing is waiting for you" description="Proposals from investigations and simulations appear here." />
      ) : (
        <ul className="divide-y divide-ink-100">
          {data.slice(0, 4).map((proposal) => (
            <li key={proposal.id}>
              <Link href={`/proposals/${proposal.id}`} className="block px-4 py-2.5 hover:bg-ink-25">
                <span className="text-xs font-medium text-brand-700">{actionTypeLabel(proposal.action_type)}</span>
                <span className="mt-0.5 block text-[13px] font-medium leading-5 text-ink-900">{proposal.title}</span>
                <span className="mt-0.5 block text-xs text-ink-500">
                  Proposed {ago(proposal.created_at)}
                  {proposal.origin === "ai_investigation" ? " by an investigation" : ""}
                </span>
              </Link>
            </li>
          ))}
          {data.length > 4 && (
            <li className="px-4 py-2">
              <PanelLink href="/proposals">All {data.length} proposals</PanelLink>
            </li>
          )}
        </ul>
      )}
    </Card>
  );
}

function Upcoming() {
  const { data, loading } = useApi<OrderList>("/orders");
  const soon = useMemo(
    () =>
      (data?.items ?? [])
        .filter((order) => {
          const days = daysUntil(order.promised_date);
          return days !== null && days <= 21;
        })
        .sort((a, b) => a.promised_date.localeCompare(b.promised_date))
        .slice(0, 6),
    [data],
  );
  return (
    <Card title="Upcoming commitments" subtitle="Orders promised in the next three weeks." flush>
      {loading && !data ? (
        <Loading rows={3} />
      ) : soon.length === 0 ? (
        <EmptyState compact title="No deliveries due in the next three weeks" />
      ) : (
        <ul className="divide-y divide-ink-100">
          {soon.map((order) => (
            <li key={order.id}>
              <Link href={`/orders/${order.id}`} className="flex items-center gap-3 px-4 py-2 hover:bg-ink-25">
                <div className="w-12 shrink-0 text-center">
                  <div className="text-[13px] font-semibold text-ink-900 tnum">{shortDate(order.promised_date).split(" ")[0]}</div>
                  <div className="text-2xs uppercase text-ink-500">{shortDate(order.promised_date).split(" ")[1]}</div>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium text-ink-900">
                    {order.number} <span className="font-normal text-ink-500">· {order.customer_name}</span>
                  </div>
                  <div className="text-xs text-ink-500">{dueText(order.promised_date)}</div>
                </div>
                <RiskBadge risk={order.risk} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function daysUntil(value: string): number | null {
  const [y, m, d] = value.split("-").map(Number);
  if (!y) return null;
  const target = Date.UTC(y, m - 1, d);
  const today = new Date();
  return Math.round((target - Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / 86_400_000);
}

function WhereProblemsAre({ data }: { data: Dashboard | null }) {
  const rows = useMemo(
    () =>
      Object.entries(data?.counts_by_type ?? {})
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1]),
    [data],
  );
  const max = Math.max(1, ...rows.map(([, c]) => c));
  return (
    <Card title="Where the problems are" subtitle="Open exceptions by kind.">
      {!data ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-ink-500">No open exceptions.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map(([type, count]) => (
            <li key={type}>
              <Link href={`/exceptions?type=${type}`} className="group block">
                <div className="flex items-baseline justify-between text-[13px]">
                  <span className="text-ink-700 group-hover:text-ink-950">{exceptionTypeLabel(type)}</span>
                  <span className="font-semibold text-ink-900 tnum">{count}</span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-ink-100">
                  <div className="h-1.5 rounded-full bg-ink-400 group-hover:bg-brand-500" style={{ width: `${(count / max) * 100}%` }} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ProductionPanel() {
  const { data, loading } = useApi<Batch[] | { items: Batch[] }>("/production/batches");
  const batches = Array.isArray(data) ? data : (data?.items ?? []);
  const inProgress = batches.filter((b) => b.status === "in_progress").length;
  const planned = batches.filter((b) => ["planned", "scheduled"].includes(b.status)).length;
  const blocked = batches.filter((b) => b.status === "blocked").length;
  const behind = batches.filter((b) => (b.delay_days ?? 0) > 0).sort((a, b) => (b.delay_days ?? 0) - (a.delay_days ?? 0));
  return (
    <Card title="Production" subtitle="Batches on the floor and in the plan." actions={<PanelLink href="/production">Production</PanelLink>}>
      {loading && !data ? (
        <Skeleton className="h-16" />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat size="sm" label="Running" value={inProgress} />
            <Stat size="sm" label="Planned" value={planned} />
            <Stat size="sm" label="Blocked" value={blocked} tone={blocked ? "bad" : "neutral"} />
          </div>
          <div className="mt-3 border-t border-ink-100 pt-2.5">
            <p className="text-xs font-medium text-ink-500">Behind schedule</p>
            {behind.length === 0 ? (
              <p className="mt-1 text-[13px] text-ink-600">Every batch is on its plan.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {behind.slice(0, 4).map((batch) => (
                  <li key={batch.id} className="flex items-baseline justify-between gap-2 text-[13px]">
                    <Link href={`/production/${batch.id}`} className="min-w-0 truncate text-ink-800 hover:text-brand-700">
                      <span className="font-medium">{batch.code}</span>{" "}
                      <span className="text-ink-500">{batch.fabric_name}</span>
                    </Link>
                    <span className="shrink-0 font-semibold text-high-text tnum">{batch.delay_days} d late</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

function MaterialsPanel() {
  const { data, loading } = useApi<Position[]>("/inventory/positions");
  const positions = data ?? [];
  const short = positions.filter((p) => Number(p.shortage ?? 0) > 0);
  const tight = positions.filter((p) => Number(p.shortage ?? 0) <= 0 && p.first_shortfall_date);
  return (
    <Card title="Material availability" subtitle="Against every planned batch, in date order." actions={<PanelLink href="/inventory">Inventory</PanelLink>}>
      {loading && !data ? (
        <Skeleton className="h-16" />
      ) : short.length + tight.length === 0 ? (
        <p className="text-[13px] text-ink-600">Every material is covered for the batches planned.</p>
      ) : (
        <ul className="space-y-2.5">
          {short.map((p) => (
            <li key={p.material_id}>
              <Link href={`/inventory/${p.material_id}`} className="group block">
                <div className="flex items-baseline justify-between gap-2 text-[13px]">
                  <span className="truncate font-medium text-ink-900 group-hover:text-brand-700">{p.material_name}</span>
                  <span className="shrink-0 font-semibold text-critical-text tnum">
                    −{num(p.shortage)} {p.unit}
                  </span>
                </div>
                <p className="text-xs text-ink-500">Short from {shortDate(p.first_shortfall_date)} even after incoming stock</p>
              </Link>
            </li>
          ))}
          {tight.map((p) => (
            <li key={p.material_id}>
              <Link href={`/inventory/${p.material_id}`} className="group block">
                <div className="flex items-baseline justify-between gap-2 text-[13px]">
                  <span className="truncate font-medium text-ink-900 group-hover:text-brand-700">{p.material_name}</span>
                  <span className="shrink-0 text-xs font-medium text-high-text">Arrives late</span>
                </div>
                <p className="text-xs text-ink-500">Needed {shortDate(p.first_shortfall_date)}, covered only by a later delivery</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SuppliersPanel() {
  const { data, loading } = useApi<Supplier[]>("/suppliers");
  const suppliers = [...(data ?? [])]
    .filter((s) => s.open_po_count > 0 || s.late_po_count > 0)
    .sort((a, b) => b.late_po_count - a.late_po_count || Number(a.on_time_rate ?? 1) - Number(b.on_time_rate ?? 1));
  return (
    <Card title="Suppliers" subtitle="With orders open against them." actions={<PanelLink href="/suppliers">Suppliers</PanelLink>}>
      {loading && !data ? (
        <Skeleton className="h-16" />
      ) : suppliers.length === 0 ? (
        <p className="text-[13px] text-ink-600">No purchase orders are open.</p>
      ) : (
        <ul className="space-y-2">
          {suppliers.slice(0, 5).map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2 text-[13px]">
              <Link href={`/suppliers/${s.id}`} className="min-w-0 truncate text-ink-800 hover:text-brand-700">
                {s.name}
              </Link>
              <span className="flex shrink-0 items-center gap-2 text-xs">
                {s.late_po_count > 0 && <span className="font-semibold text-critical-text">{s.late_po_count} late</span>}
                <span className="text-ink-500 tnum" title="Share of past purchase orders received by their expected date">
                  {s.on_time_rate === null ? "no history" : `${Math.round(Number(s.on_time_rate) * 100)}% on time`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function RecentActivity() {
  const { data, loading } = useApi<AuditEvent[]>("/audit", { limit: 8 });
  return (
    <Card title="Recent activity" subtitle="What changed, and who or what changed it." actions={<PanelLink href="/audit">Audit trail</PanelLink>} flush>
      {loading && !data ? (
        <Loading rows={4} />
      ) : !data || data.length === 0 ? (
        <EmptyState compact title="Nothing recorded yet" />
      ) : (
        <ul className="divide-y divide-ink-100">
          {data.slice(0, 8).map((event) => (
            <li key={event.id} className="flex items-baseline gap-3 px-4 py-2 text-[13px]">
              <span className="w-24 shrink-0 text-xs text-ink-500 tnum">{ago(event.occurred_at)}</span>
              <ActorTag event={event} />
              <span className="min-w-0 flex-1 truncate text-ink-800" title={event.summary}>
                {event.summary}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

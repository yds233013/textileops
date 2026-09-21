"use client";

import type { Shipment } from "@/lib/types";

const STAGES = ["Planned", "Dispatched", "In transit", "Arrived"] as const;

/** How far a shipment has got. Dispatch is not arrival, and the track says so. */
export function reached(status: string): number {
  if (status === "delivered") return 3;
  if (["in_transit", "delayed"].includes(status)) return 2;
  if (status === "dispatched") return 1;
  return 0;
}

export function Track({ shipment }: { shipment: Shipment }) {
  if (shipment.status === "cancelled") return <span className="text-xs text-ink-500">Cancelled</span>;
  const at = reached(shipment.status);
  const overdue = shipment.days_late > 0 && shipment.status !== "delivered";
  const arrivedLate = shipment.status === "delivered" && shipment.delivered_late;
  return (
    <div className="w-56" role="img" aria-label={`${STAGES[at]}${overdue ? `, ${shipment.days_late} days overdue` : ""}`}>
      <div className="flex items-center">
        {STAGES.map((stage, index) => {
          const done = index <= at;
          const current = index === at;
          const colour =
            current && overdue
              ? "bg-critical-solid ring-critical-border"
              : current && at === 3
                ? arrivedLate
                  ? "bg-high-solid ring-high-border"
                  : "bg-good-solid ring-good-border"
                : done
                  ? "bg-info-solid ring-info-border"
                  : "bg-white ring-ink-200";
          return (
            <div key={stage} className="flex flex-1 items-center last:flex-none">
              <span aria-hidden className={`h-2.5 w-2.5 shrink-0 rounded-full ring-2 ${colour} ${current ? "scale-125" : ""}`} />
              {index < STAGES.length - 1 && (
                <span aria-hidden className={`h-0.5 flex-1 ${index < at ? "bg-info-solid" : "bg-ink-150"}`} />
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex items-baseline justify-between gap-2 text-xs">
        <span className={overdue ? "font-semibold text-critical-text" : at === 3 ? (arrivedLate ? "font-medium text-high-text" : "font-medium text-good-text") : "font-medium text-ink-800"}>
          {STAGES[at]}
          {overdue ? ` · ${shipment.days_late} days overdue` : arrivedLate ? ` · ${shipment.days_late} days late` : ""}
        </span>
      </div>
    </div>
  );
}

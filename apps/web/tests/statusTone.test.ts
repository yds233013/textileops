import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { READINESS_TONE } from "@/components/ui";

/**
 * The status pill takes a bare string from the API and colours it. Anything
 * missing from the map falls back to neutral grey, which reads as "fine" — so
 * a status the backend adds later would arrive on screen looking reassuring
 * regardless of what it means. A QC *reject* rendered in the same grey as
 * *not applicable* is exactly that failure, and it shipped.
 *
 * This test reads the backend enums directly rather than restating them, so
 * the two cannot drift apart silently.
 */
const ENUMS_PATH = path.resolve(
  __dirname,
  "../../api/textileops/models/enums.py",
);

/** Enums whose values are rendered as status pills in the operations UI. */
const RENDERED_ENUMS = [
  "SalesOrderStatus",
  "PurchaseOrderStatus",
  "QCOutcome",
  "ShipmentStatus",
  "DocumentStatus",
  "ExceptionStatus",
  "ProposalStatus",
  "ExecutionStatus",
  "LotStatus",
  "ProductionStatus",
];

function valuesOf(source: string, enumName: string): string[] {
  const start = source.indexOf(`class ${enumName}(StrEnum):`);
  if (start === -1) return [];
  const rest = source.slice(start);
  const end = rest.indexOf("\nclass ", 1);
  const body = end === -1 ? rest : rest.slice(0, end);
  return [...body.matchAll(/^\s{4}[A-Z0-9_]+ = "([a-z0-9_]+)"$/gm)].map((m) => m[1]);
}

describe("status pill colours", () => {
  const source = readFileSync(ENUMS_PATH, "utf8");

  it("reads the backend enums it is checking against", () => {
    // Guards the test itself: a moved file would otherwise make every
    // assertion below vacuously pass.
    for (const name of RENDERED_ENUMS) {
      expect(valuesOf(source, name).length, `${name} had no values`).toBeGreaterThan(0);
    }
  });

  it.each(RENDERED_ENUMS)("gives every %s value a deliberate tone", (enumName) => {
    const missing = valuesOf(source, enumName).filter(
      (value) => !(value in READINESS_TONE),
    );
    expect(
      missing,
      `${enumName} values would render neutral grey by accident: ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("never colours a failure as success", () => {
    for (const value of ["reject", "rejected", "failed", "blocked", "short", "delayed"]) {
      expect(READINESS_TONE[value], `${value} must not read as good`).toBe("bad");
    }
  });

  it("does not present a dismissal or a cancellation as a success", () => {
    // Dismissing an exception is a judgement that it did not matter; it is not
    // a problem that got fixed, and green would claim that it was.
    for (const value of ["dismissed", "cancelled", "not_inspected"]) {
      expect(READINESS_TONE[value]).toBe("neutral");
    }
  });

  it("covers the order roll-up statuses the API derives", () => {
    // These are computed in services/orders.py rather than stored as enums, so
    // the enum sweep above cannot see them.
    for (const value of [
      "partially_inspected",
      "partially_cancelled",
      "materials_not_covered",
      "nothing_planned",
      "nothing_to_ship",
      "not_shipped",
      "not_started",
      "not_applicable",
    ]) {
      expect(value in READINESS_TONE, `${value} is unmapped`).toBe(true);
    }
  });
});

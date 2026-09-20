import { describe, expect, it } from "vitest";

/**
 * Wording and colour checked against the data behind them.
 *
 * These are pure-function tests of the decisions the pages make, not render
 * tests: the point is the *rule*, and a rule stated once here is harder to
 * regress than one buried in JSX. Each encodes a case where the screen said
 * something stronger, or more comforting, than the backend knew.
 */

// --- The decisions, extracted exactly as the pages make them ---------------

/** Which banner a proposal decision gets. */
function bannerTone(outcome: string): "good" | "medium" | "critical" {
  if (outcome === "failed") return "critical";
  if (outcome === "awaiting_external") return "medium";
  return "good";
}

/** What the order page says when there is no estimated completion date. */
function completionText(
  estimated: string | null,
  reason: string | null,
): { value: string; hint: string } {
  if (estimated !== null) return { value: estimated, hint: "" };
  if (reason === null) {
    return {
      value: "Nothing left to make",
      hint: "Everything on this order has been produced or shipped.",
    };
  }
  if (reason === "materials_not_covered") {
    return {
      value: "No date yet",
      hint: "Production is planned, but its materials are not covered, so no completion date can be worked out yet.",
    };
  }
  return {
    value: "No date yet",
    hint: "Nothing is planned for the outstanding quantity.",
  };
}

const UNTRUSTED_EVIDENCE_KINDS = new Set(["message", "document", "ai_hypothesis"]);

describe("a failed execution is not announced as a success", () => {
  it("colours a failed execution as a failure", () => {
    // The request succeeded (HTTP 200); the action did not. Both used to land
    // in the same success-green box, so an operator whose ETA revision had
    // failed to apply saw green and moved on.
    expect(bannerTone("failed")).toBe("critical");
  });

  it("does not present an unsent draft as a completed action", () => {
    expect(bannerTone("awaiting_external")).toBe("medium");
  });

  it("still shows a real success as a success", () => {
    expect(bannerTone("ok")).toBe("good");
  });
});

describe("a finished order is not described as an impossible one", () => {
  it("says the work is done when there is nothing left to make", () => {
    // A fully shipped order has no estimated completion, and the page used to
    // print "No achievable date — nothing in stock and nothing planned".
    const { value, hint } = completionText(null, null);
    expect(value).toBe("Nothing left to make");
    expect(hint).toMatch(/produced or shipped/);
    expect(hint).not.toMatch(/nothing planned/i);
  });

  it("distinguishes uncovered materials from nothing being planned", () => {
    const uncovered = completionText(null, "materials_not_covered");
    const unplanned = completionText(null, "nothing_planned");
    expect(uncovered.hint).not.toBe(unplanned.hint);
    expect(uncovered.hint).toMatch(/materials are not covered/);
    expect(unplanned.hint).toMatch(/[Nn]othing is planned/);
  });

  it("never claims a date is unachievable", () => {
    // "No achievable date" is a prediction. The system only knows it has not
    // worked one out.
    for (const reason of [null, "materials_not_covered", "nothing_planned"]) {
      expect(completionText(null, reason).value).not.toMatch(/achievable/i);
    }
  });
});

describe("evidence written by someone else is marked as theirs", () => {
  it("treats message, document and AI-hypothesis evidence as third-party", () => {
    // The card used to carry a blanket subtitle saying every figure came from
    // our own records, above a list that includes a supplier's prose verbatim
    // — the very text the system fences before it reaches a model.
    expect(UNTRUSTED_EVIDENCE_KINDS.has("message")).toBe(true);
    expect(UNTRUSTED_EVIDENCE_KINDS.has("document")).toBe(true);
    expect(UNTRUSTED_EVIDENCE_KINDS.has("ai_hypothesis")).toBe(true);
  });

  it("treats calculations and records as ours", () => {
    expect(UNTRUSTED_EVIDENCE_KINDS.has("calculation")).toBe(false);
    expect(UNTRUSTED_EVIDENCE_KINDS.has("record")).toBe(false);
    expect(UNTRUSTED_EVIDENCE_KINDS.has("timeline")).toBe(false);
  });
});

describe("shipment lateness", () => {
  /** Mirrors _shipment_out in the API. */
  function daysLate(
    expected: number | null,
    actual: number | null,
    today: number,
  ): { days: number; deliveredLate: boolean } {
    if (expected === null) return { days: 0, deliveredLate: false };
    const reference = actual ?? today;
    const days = reference > expected ? reference - expected : 0;
    return { days, deliveredLate: actual !== null && days > 0 };
  }

  it("marks a delivery that arrived late", () => {
    // This was the defect: lateness was only computed when the shipment had
    // *not* arrived, so a delivery twelve days overdue showed the same "—" as
    // one that arrived on time.
    const { days, deliveredLate } = daysLate(10, 22, 30);
    expect(days).toBe(12);
    expect(deliveredLate).toBe(true);
  });

  it("still marks one that has not arrived", () => {
    const { days, deliveredLate } = daysLate(10, null, 18);
    expect(days).toBe(8);
    expect(deliveredLate).toBe(false);
  });

  it("marks an on-time delivery as not late", () => {
    expect(daysLate(10, 9, 30).days).toBe(0);
  });
});

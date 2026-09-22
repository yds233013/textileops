import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { forecast, OrderPipeline } from "@/components/orders";
import { originText } from "@/components/proposals";
import { measurementVerdict } from "@/components/quality";
import { reached, Track } from "@/components/shipments";
import { contentWidth } from "@/components/shell";
import { ConfirmDialog, ProvenanceTag, Segmented } from "@/components/ui";
import { businessToday, setBusinessDate } from "@/lib/format";
import { exceptionTypeLabel, statusLabel } from "@/lib/labels";
import type { Measurement, OrderSummary, Proposal, Shipment } from "@/lib/types";

/**
 * Presentation rules: the places where the screen could say something stronger,
 * or more comforting, than the data behind it. Each test names the misreading
 * it prevents.
 */

const isoDaysFromNow = (days: number) => {
  setBusinessDate("2026-09-22");
  const d = businessToday();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

describe("order forecast", () => {
  it("never presents a past date for unfinished work as a forecast", () => {
    const f = forecast({ estimated_completion: isoDaysFromNow(-3), completion_unknown_reason: null, days_ahead: 0 });
    expect(f.value).toBe("Overdue");
    expect(f.tone).toBe("bad");
    expect(f.hint).toMatch(/no revised date/);
  });

  it("says how late a forecast is against the promise", () => {
    const f = forecast({ estimated_completion: isoDaysFromNow(10), completion_unknown_reason: null, days_ahead: -4 });
    expect(f.hint).toBe("4 days after promise");
    expect(f.tone).toBe("bad");
  });

  it("distinguishes a finished order from one nobody has planned", () => {
    // A fully shipped order once read "No achievable date" — a completed job
    // presented as an impossible one.
    expect(forecast({ estimated_completion: null, completion_unknown_reason: null, days_ahead: null }).value).toBe(
      "Nothing left to make",
    );
    const unplanned = forecast({ estimated_completion: null, completion_unknown_reason: "nothing_planned", days_ahead: null });
    expect(unplanned.value).toBe("No date yet");
    expect(unplanned.tone).toBe("warn");
    const uncovered = forecast({ estimated_completion: null, completion_unknown_reason: "materials_not_covered", days_ahead: null });
    expect(uncovered.tone).toBe("bad");
  });
});

describe("order pipeline strip", () => {
  it("states every stage in words for assistive technology", () => {
    const order = {
      material_readiness: "short",
      production_status: "in_progress",
      qc_status: "not_inspected",
      shipment_status: "not_shipped",
    } as OrderSummary;
    render(<OrderPipeline order={order} />);
    expect(
      screen.getByRole("img", {
        name: "Materials: Short, Production: In progress, QC: Not inspected, Shipment: Not shipped",
      }),
    ).toBeInTheDocument();
  });
});

describe("shipment track", () => {
  const base = { days_late: 0, delivered_late: false } as Shipment;

  it("never shows a dispatched shipment as arrived", () => {
    expect(reached("dispatched")).toBe(1);
    expect(reached("in_transit")).toBe(2);
    expect(reached("delivered")).toBe(3);
    render(<Track shipment={{ ...base, status: "in_transit" }} />);
    expect(screen.queryByText(/Arrived/)).not.toBeInTheDocument();
  });

  it("says how overdue a shipment still on the road is", () => {
    render(<Track shipment={{ ...base, status: "in_transit", days_late: 6 }} />);
    expect(screen.getByRole("img", { name: "In transit, 6 days overdue" })).toBeInTheDocument();
  });
});

describe("QC measurement verdicts", () => {
  const m = (overrides: Partial<Measurement>): Measurement => ({
    kind: "shade",
    label: null,
    observed_value: null,
    observed_text: null,
    target_value: null,
    tolerance_low: null,
    tolerance_high: null,
    unit_text: null,
    result: "not_assessed",
    ...overrides,
  });

  it("never treats a missing reading as a pass", () => {
    const verdict = measurementVerdict(m({}));
    expect(verdict.label).toBe("Not measured");
    expect(verdict.tone).not.toBe("ok");
  });

  it("shows an inspector's visual judgement as a judgement, not as 'not assessed'", () => {
    // The shade check that rejected B-1035 rendered "Not assessed".
    const verdict = measurementVerdict(m({ observed_text: "Off-shade vs approved swatch" }));
    expect(verdict.label).toBe("Inspector's judgement");
  });

  it("reports a measured value against its band", () => {
    expect(measurementVerdict(m({ result: "out_of_tolerance" })).tone).toBe("bad");
    expect(measurementVerdict(m({ result: "within_tolerance" })).tone).toBe("ok");
  });
});

describe("labels", () => {
  it("does not mangle acronyms", () => {
    expect(exceptionTypeLabel("QC_FAILURE")).toBe("QC failure");
    expect(exceptionTypeLabel("PO_LATE")).toBe("Purchase order overdue");
    expect(statusLabel("pending_approval")).toBe("Awaiting approval");
  });
});

describe("proposal origin", () => {
  it("never calls a rule-engine investigation AI", () => {
    const proposal = { origin: "ai_investigation", model: "deterministic-rules-v1" } as Proposal;
    expect(originText(proposal)).toBe("From an investigation (rule engine)");
    expect(originText({ ...proposal, model: "claude-sonnet-5" })).toBe("From an AI investigation");
  });

  it("names the person who raised a proposal", () => {
    expect(originText({ origin: "human", created_by_name: "Divya Narayanan" } as Proposal)).toBe(
      "Raised by Divya Narayanan",
    );
  });
});

describe("content widths", () => {
  it("gives dense lists room and keeps detail pages composed", () => {
    expect(contentWidth("/orders")).toBe("max-w-wide");
    expect(contentWidth("/orders/abc")).toBe("max-w-page");
    expect(contentWidth("/settings")).toBe("max-w-narrow");
    expect(contentWidth("/proposals")).toBe("max-w-narrow");
    expect(contentWidth("/")).toBe("max-w-page");
  });
});

describe("provenance", () => {
  it("labels model output as an interpretation, with an explanation on hover", () => {
    render(<ProvenanceTag kind="ai" />);
    const tag = screen.getByText("AI interpretation");
    expect(tag.closest("span")).toHaveAttribute("title", expect.stringMatching(/cannot change anything/));
  });
});

describe("interaction", () => {
  it("closes a confirmation with Escape, without confirming", async () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(<ConfirmDialog open title="Dispatch SHP-1" body="Sure?" onConfirm={onConfirm} onCancel={onCancel} />);
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("a destructive confirmation is visibly different from an ordinary one", () => {
    render(<ConfirmDialog open tone="danger" title="Dismiss" body="x" confirmLabel="Dismiss" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Dismiss" }).className).toMatch(/critical/);
  });

  it("segmented filters are radio groups that report the choice", async () => {
    const onChange = vi.fn();
    render(
      <Segmented
        label="Risk"
        value="all"
        onChange={onChange}
        options={[
          { value: "all", label: "All", count: 8 },
          { value: "late", label: "Late", count: 1 },
        ]}
      />,
    );
    expect(screen.getByRole("radiogroup", { name: "Risk" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /All/ })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("radio", { name: /Late/ }));
    expect(onChange).toHaveBeenCalledWith("late");
  });
});

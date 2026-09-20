import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AttentionCard } from "@/components/attention";
import type { AttentionCard as Card } from "@/lib/types";

function makeCard(overrides: Partial<Card> = {}): Card {
  return {
    exception_id: "11111111-1111-1111-1111-111111111111",
    code: "EXC-00007",
    exception_type: "SUPPLIER_DELAY",
    severity: "high",
    status: "open",
    priority_score: 3080,
    what: "Sri Balaji Spinning Mills delayed PO-00002 by 6 day(s)",
    why: "Original date 2026-09-23, now 2026-09-29. Reason given: ring frame breakdown.",
    impact_headline: "Two batches for Meridian Apparel depend on this yarn.",
    impact_metrics: [
      { key: "delay_days", label: "Days pushed out", value: 6, unit: "days", basis: "calculated", note: null },
      {
        key: "margin_exposure",
        label: "Margin exposure",
        value: null,
        unit: null,
        basis: "unavailable",
        note: "Cost of goods is not recorded against sales order lines.",
      },
    ],
    recommended_action: "Ask for a firm revised date and whether a part shipment can be released.",
    customers_affected: ["Meridian Apparel Ltd"],
    revenue_exposure: "10050.00",
    revenue_basis: "calculated",
    revenue_note: null,
    currency: "GBP",
    detected_at: new Date().toISOString(),
    age_hours: 5,
    has_investigation: false,
    pending_proposal_count: 1,
    links: { order: "22222222-2222-2222-2222-222222222222", purchase_order: null, batch: null, material: null, shipment: null },
    ...overrides,
  };
}

describe("AttentionCard", () => {
  it("answers what, why, impact and what to do next", () => {
    render(<AttentionCard card={makeCard()} />);
    expect(screen.getByText(/delayed PO-00002 by 6 day/)).toBeInTheDocument();
    expect(screen.getByText(/ring frame breakdown/)).toBeInTheDocument();
    expect(screen.getByText(/Two batches for Meridian Apparel/)).toBeInTheDocument();
    expect(screen.getByText(/firm revised date/)).toBeInTheDocument();
  });

  it("shows an unavailable metric as unavailable, never as zero", () => {
    render(<AttentionCard card={makeCard()} />);
    const marginChip = screen.getByText(/Margin exposure/);
    expect(marginChip.textContent).toMatch(/not available/i);
    expect(marginChip.textContent).not.toMatch(/\b0\b/);
  });

  it("says when revenue exposure is unavailable instead of going quiet", () => {
    // Dropping the chip entirely made an exception of unknown cost look
    // identical to one that costs nothing — the flattering reading.
    render(
      <AttentionCard
        card={makeCard({
          revenue_exposure: null,
          revenue_basis: "unavailable",
          revenue_note: "No unit prices are recorded on the affected order lines.",
        })}
      />,
    );
    const chip = screen.getByTitle(
      "No unit prices are recorded on the affected order lines.",
    );
    expect(chip).toHaveTextContent(/revenue exposure/i);
    expect(chip).toHaveTextContent(/not available/i);
  });

  it("shows revenue exposure with its currency", () => {
    render(<AttentionCard card={makeCard()} />);
    expect(screen.getByText("£10,050.00")).toBeInTheDocument();
  });

  it("marks a partial financial basis rather than implying a complete total", () => {
    render(<AttentionCard card={makeCard({ revenue_basis: "partial" })} />);
    expect(screen.getByText(/\(partial\)/)).toBeInTheDocument();
  });

  it("links to the investigation and to the affected order", () => {
    render(<AttentionCard card={makeCard()} />);
    expect(screen.getByRole("link", { name: /Open investigation/ })).toHaveAttribute(
      "href",
      "/exceptions/11111111-1111-1111-1111-111111111111",
    );
    expect(screen.getByRole("link", { name: "Order" })).toHaveAttribute(
      "href",
      "/orders/22222222-2222-2222-2222-222222222222",
    );
  });

  it("surfaces that an approval is waiting", () => {
    render(<AttentionCard card={makeCard()} />);
    expect(screen.getByText(/1 awaiting approval/)).toBeInTheDocument();
  });
});

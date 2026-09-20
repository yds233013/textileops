import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PilotModeBanner } from "@/components/pilot";

vi.mock("@/lib/hooks", () => ({
  useApi: vi.fn(),
}));

import { useApi } from "@/lib/hooks";

const mocked = vi.mocked(useApi);

function withSettings(value: unknown) {
  mocked.mockReturnValue({
    data: value,
    error: null,
    loading: false,
    refresh: vi.fn(),
  } as never);
}

describe("pilot mode banner", () => {
  it("says nothing when the server is not in pilot mode", () => {
    withSettings({ pilot_mode: false, pilot_mode_note: "irrelevant" });
    const { container } = render(<PilotModeBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("explains why changes are waiting, not just that a mode is on", () => {
    // "Pilot mode" on its own tells an operator nothing about why a supplier's
    // date change is sitting in a queue instead of having happened.
    withSettings({
      pilot_mode: true,
      pilot_mode_note:
        "TextileOps is ingesting, reconciling, calculating and proposing, but " +
        "will not change a delivery date, a purchase order or stock by itself. " +
        "Every change waits for someone to confirm it.",
    });
    render(<PilotModeBanner />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent(/pilot mode/i);
    expect(banner).toHaveTextContent(/will not change a delivery date/i);
    expect(banner).toHaveTextContent(/waits for someone to confirm/i);
  });

  it("stays quiet while the setting is still loading", () => {
    // Showing the banner before the answer arrives would be a claim about the
    // server that has not been checked yet.
    withSettings(undefined);
    const { container } = render(<PilotModeBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});

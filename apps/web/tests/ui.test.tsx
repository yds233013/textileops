import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  RiskBadge,
  StatusPill,
  Unavailable,
} from "@/components/ui";

describe("status components", () => {
  it("labels risk in the words operators use", () => {
    render(<RiskBadge risk="at_risk" />);
    expect(screen.getByText("At risk")).toBeInTheDocument();
  });

  it("renders readable status pills", () => {
    render(<StatusPill value="partially_shipped" />);
    expect(screen.getByText("Partially shipped")).toBeInTheDocument();
  });

  it("says a figure is unavailable and why", () => {
    render(<Unavailable reason="No unit prices recorded." />);
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getByText(/No unit prices recorded/)).toBeInTheDocument();
  });
});

describe("states", () => {
  it("explains an empty result instead of showing a blank screen", () => {
    render(<EmptyState title="Nothing needs your attention" description="All clear." />);
    expect(screen.getByText("Nothing needs your attention")).toBeInTheDocument();
    expect(screen.getByText("All clear.")).toBeInTheDocument();
  });

  it("announces errors to assistive technology and offers a retry", async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new Error("Connection refused")} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Connection refused");
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("ConfirmDialog", () => {
  it("does not render when closed", () => {
    render(
      <ConfirmDialog open={false} title="Approve" body="Sure?" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requires an explicit confirmation before acting", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Approve this action"
        body="TextileOps will carry this out immediately."
        confirmLabel="Approve"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAccessibleName("Approve this action");
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});

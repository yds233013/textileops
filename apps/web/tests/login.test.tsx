import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const demoInfo = vi.fn();
const demoLogin = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { demoInfo: () => demoInfo(), demoLogin: () => demoLogin(), login: vi.fn() },
  rememberUser: vi.fn(),
}));

import LoginPage from "@/app/login/page";
import { safeNext } from "@/lib/session";

/**
 * The login page is the first thing a person sent the demo link sees. It must
 * offer the demo only when the server says demo mode is on, and must never
 * describe configuration to a visitor.
 */
describe("login", () => {
  beforeEach(() => {
    replace.mockReset();
    demoInfo.mockReset();
    demoLogin.mockReset();
  });

  it("offers one-click entry when the server is in demo mode, and uses it", async () => {
    demoInfo.mockResolvedValue({ enabled: true, full_name: "Ramesh Kaveri" });
    demoLogin.mockResolvedValue({ user: {} });
    render(<LoginPage />);
    const button = await screen.findByRole("button", { name: /Explore the demo/ });
    expect(screen.getByText(/signed in as Ramesh Kaveri, the owner/)).toBeInTheDocument();
    await userEvent.click(button);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("does not offer a demo when the server says there is none", async () => {
    demoInfo.mockResolvedValue({ enabled: false, full_name: null });
    render(<LoginPage />);
    await waitFor(() => expect(demoInfo).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Explore the demo/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("never tells a visitor about environment variables or default passwords", async () => {
    demoInfo.mockResolvedValue({ enabled: true, full_name: "Ramesh Kaveri" });
    const { container } = render(<LoginPage />);
    await screen.findByRole("button", { name: /Explore the demo/ });
    expect(container.textContent).not.toMatch(/DEMO_PASSWORD|textileops by default|\.env/);
  });

  it("returns to the page the visitor was sent from, and only to this site", () => {
    expect(safeNext("?next=%2Forders%2Fabc%3Frisk%3Dlate")).toBe("/orders/abc?risk=late");
    expect(safeNext("")).toBe("/");
    expect(safeNext("?next=https%3A%2F%2Fevil.example")).toBe("/");
    expect(safeNext("?next=%2F%2Fevil.example")).toBe("/");
    expect(safeNext("?next=%2F%5Cevil.example")).toBe("/");
  });
});

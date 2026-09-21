import { expect, test } from "@playwright/test";

/**
 * Every route renders, without a console error, without pushing the page
 * sideways, and with a heading — at desktop, laptop and phone widths.
 */
const API = process.env.API ?? "http://localhost:8000/api/v1";

const ROUTES = [
  "/", "/exceptions", "/orders", "/proposals", "/shipments", "/purchase-orders", "/suppliers",
  "/inventory", "/materials", "/production", "/quality", "/documents", "/reconciliation",
  "/audit", "/metrics", "/simulation", "/settings",
];

test.beforeEach(async ({ context }) => {
  const response = await fetch(`${API}/auth/demo-login`, { method: "POST" });
  test.skip(!response.ok, "The API is not in demo mode; these checks sign in through it.");
  const login = await response.json();
  await context.addInitScript(
    ([token, user]) => {
      localStorage.setItem("textileops.token", token);
      localStorage.setItem("textileops.user", JSON.stringify(user));
    },
    [login.access_token, login.user],
  );
});

for (const route of ROUTES) {
  test(`renders ${route}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(route, { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(0);
    expect(errors).toEqual([]);
  });
}

test("the approval workflow is reachable from the command centre", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.getByRole("link", { name: /Awaiting your approval/ }).first().click();
  await expect(page).toHaveURL(/\/proposals$/);
  await page.getByRole("link", { name: /Review/ }).first().click();
  await expect(page.getByRole("button", { name: /Approve/ })).toBeVisible();
});

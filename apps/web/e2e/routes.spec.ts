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

test.beforeEach(async ({ context }, testInfo) => {
  if (testInfo.title.startsWith("session:")) return;
  // Sign in the way the browser does: through the web origin's proxy, which
  // hands back the HttpOnly session cookie into this context's cookie jar.
  const response = await context.request.post("/api/v1/auth/demo-login", {
    headers: { "x-textileops-client": "web" },
  });
  test.skip(!response.ok(), "The API is not in demo mode; these checks sign in through it.");
});

test("session: a signed-out visitor is sent to sign in, then returned to the page", async ({ page }) => {
  await page.goto("/orders?risk=late");
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByRole("button", { name: /Explore the demo/ }).click();
  await expect(page).toHaveURL(/\/orders\?risk=late$/);
  await expect(page.getByRole("heading", { level: 1, name: "Customer orders" })).toBeVisible();
});

test("session: the token is never readable by the page, and sign-out ends the session", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /Explore the demo/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Command centre" })).toBeVisible();
  const cookie = (await context.cookies()).find((c) => c.name === "textileops_session");
  expect(cookie?.httpOnly).toBe(true);
  const visible = await page.evaluate(() => document.cookie + JSON.stringify({ ...localStorage }));
  expect(visible).not.toContain(cookie!.value);
  await page.locator('button[aria-haspopup="menu"]').click();
  await page.getByRole("menuitem", { name: /Sign out/ }).click();
  // Sign-out waits for the server to clear the cookie; under three parallel
  // browsers on one small container that can take longer than the default 5 s.
  await expect(page).toHaveURL(/\/login/, { timeout: 20_000 });
  await page.goto("/exceptions");
  await expect(page).toHaveURL(/\/login/);
});

for (const route of ROUTES) {
  test(`renders ${route}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(route, { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Every screen, at every width, says the data is invented.
    await expect(page.locator('[title*="fictional company"]')).toBeVisible();
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

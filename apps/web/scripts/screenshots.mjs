// Full-page screenshots of every route, signed in through demo mode.
//
//   WEB=http://localhost:3100 API=http://localhost:8100/api/v1 \
//     node scripts/screenshots.mjs [outDir] [width]
//
// A development aid for reviewing layout, not a test. Requires DEMO_MODE on the
// API, because it signs in without a password.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const WEB = process.env.WEB ?? "http://localhost:3100";
const API = process.env.API ?? "http://localhost:8100/api/v1";
const out = process.argv[2] ?? "/tmp/textileops-shots";
const width = Number(process.argv[3] ?? 1440);
const only = process.env.ONLY ? process.env.ONLY.split(",") : null;
mkdirSync(out, { recursive: true });

const login = await (await fetch(`${API}/auth/demo-login`, { method: "POST" })).json();
const token = login.access_token;
const get = async (path) =>
  (await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } })).json();

const items = (x) => (Array.isArray(x) ? x : x?.items ?? []);
const first = (list, key = "id") => items(list)[0]?.[key] ?? null;
const exceptions = await get("/exceptions");
const orders = await get("/orders");
const pos = await get("/purchase-orders");
const batches = await get("/production/batches");
const suppliers = await get("/suppliers");
const positions = await get("/inventory/positions");
const proposals = await get("/proposals");
const documents = await get("/documents");

const routes = [
  ["login", "/login"],
  ["dashboard", "/"],
  ["exceptions", "/exceptions"],
  ["exception-detail", first(exceptions) && `/exceptions/${first(exceptions)}`],
  [
    "exception-investigated",
    items(exceptions).find((e) => e.investigated_at) &&
      `/exceptions/${items(exceptions).find((e) => e.investigated_at).id}`,
  ],
  ["orders", "/orders"],
  ["order-detail", first(orders) && `/orders/${first(orders)}`],
  ["proposals", "/proposals"],
  ["proposal-detail", first(proposals) && `/proposals/${first(proposals)}`],
  ["shipments", "/shipments"],
  ["purchase-orders", "/purchase-orders"],
  ["po-detail", first(pos) && `/purchase-orders/${first(pos)}`],
  ["suppliers", "/suppliers"],
  ["supplier-detail", first(suppliers) && `/suppliers/${first(suppliers)}`],
  ["inventory", "/inventory"],
  ["inventory-detail", first(positions, "material_id") && `/inventory/${first(positions, "material_id")}`],
  ["materials", "/materials"],
  ["production", "/production"],
  ["batch-detail", first(batches) && `/production/${first(batches)}`],
  ["quality", "/quality"],
  ["documents", "/documents"],
  ["document-detail", first(documents) && `/documents/${first(documents)}`],
  ["reconciliation", "/reconciliation"],
  ["audit", "/audit"],
  ["metrics", "/metrics"],
  ["simulation", "/simulation"],
  ["settings", "/settings"],
].filter(([name, path]) => path && (!only || only.includes(name)));

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
await context.addInitScript(
  ([t, u]) => {
    if (location.pathname !== "/login") {
      localStorage.setItem("textileops.token", t);
      localStorage.setItem("textileops.user", JSON.stringify(u));
    }
  },
  [token, login.user],
);
const page = await context.newPage();
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(`${page.url()} console: ${m.text()}`));
page.on("pageerror", (e) => problems.push(`${page.url()} pageerror: ${e.message}`));

for (const [name, path] of routes) {
  const started = Date.now();
  await page.goto(`${WEB}${path}`, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(400);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 0) problems.push(`${path}: horizontal overflow ${overflow}px`);
  await page.screenshot({ path: `${out}/${name}-${width}.png`, fullPage: true });
  console.log(`${name.padEnd(18)} ${path.padEnd(52)} ${Date.now() - started}ms`);
}
await browser.close();
if (problems.length) console.log("\nPROBLEMS:\n" + problems.join("\n"));

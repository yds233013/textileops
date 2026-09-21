import { defineConfig } from "@playwright/test";

/**
 * Browser checks against a running stack (API in demo mode + web).
 *
 *   WEB=http://localhost:3100 API=http://localhost:8100/api/v1 npm run e2e
 *
 * Not part of scripts/verify.sh: it needs servers, which the unit suites do not.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: process.env.WEB ?? "http://localhost:3000" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "laptop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "phone", use: { viewport: { width: 390, height: 844 } } },
  ],
});

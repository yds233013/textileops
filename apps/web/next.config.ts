import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The floating dev badge sat on top of the navigation in every review.
  devIndicators: false,
  poweredByHeader: false,
  // This app has its own lockfile inside a monorepo; pin the trace root so the
  // build does not guess at a parent directory.
  outputFileTracingRoot: __dirname,
  // The API is a separate service; the browser talks to it directly using
  // NEXT_PUBLIC_API_BASE_URL. No secrets are ever exposed to the client.
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1",
  },
};

export default config;

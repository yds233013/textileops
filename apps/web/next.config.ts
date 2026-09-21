import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The floating dev badge sat on top of the navigation in every review.
  devIndicators: false,
  poweredByHeader: false,
  // This app has its own lockfile inside a monorepo; pin the trace root so the
  // build does not guess at a parent directory.
  outputFileTracingRoot: __dirname,
  // A self-contained server bundle for the container image.
  output: "standalone",
  // The API is a separate service. In a deployment the browser calls /api/v1 on
  // this origin and app/api/v1/[...path]/route.ts forwards it to API_ORIGIN at
  // request time. No secret is ever exposed to the client: the model provider's
  // key exists only in the API's environment.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
};

export default config;

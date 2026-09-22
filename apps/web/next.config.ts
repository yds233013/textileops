import type { NextConfig } from "next";

/**
 * Content Security Policy for production builds. Everything comes from this
 * origin — fonts are self-hosted, the API is proxied — so the policy can be
 * strict about sources. 'unsafe-inline' on scripts is what Next.js's inline
 * hydration data needs without per-request nonces; frame-ancestors, object-src
 * and base-uri close the other doors. Development is exempt: hot reload needs
 * eval and a direct API origin.
 */
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

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
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY }]
            : []),
        ],
      },
    ];
  },
};

export default config;

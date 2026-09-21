import type { Metadata, Viewport } from "next";
import { AppShell } from "@/components/shell";
import "@fontsource-variable/inter";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "TextileOps", template: "%s · TextileOps" },
  description:
    "Operations control for a textile manufacturer: what needs attention, why, what it costs, and what to do next.",
  applicationName: "TextileOps",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#161a22",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

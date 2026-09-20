import type { Metadata } from "next";
import { AppShell } from "@/components/shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "TextileOps",
  description: "Operations control for a textile business.",
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

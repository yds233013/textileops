"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearSession, getStoredUser, getToken } from "@/lib/api";
import type { User } from "@/lib/types";
import { GlobalSearch } from "./search";
import { SideNav } from "./nav";
import { Button } from "./ui";

/** Application chrome. Redirects to the sign-in page when there is no session. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (pathname === "/login") {
      setChecked(true);
      return;
    }
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(getStoredUser<User>());
    setChecked(true);
  }, [pathname, router]);

  useEffect(() => setNavOpen(false), [pathname]);

  if (pathname === "/login") return <>{children}</>;
  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-ink-500">
        Checking your session…
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <button
            type="button"
            aria-label="Toggle navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen((open) => !open)}
            className="rounded p-1.5 text-ink-600 hover:bg-ink-100 lg:hidden"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden fill="currentColor">
              <rect y="3" width="18" height="1.6" rx="0.8" />
              <rect y="8.2" width="18" height="1.6" rx="0.8" />
              <rect y="13.4" width="18" height="1.6" rx="0.8" />
            </svg>
          </button>
          <Link href="/" className="flex shrink-0 items-baseline gap-1.5">
            <span className="text-base font-semibold tracking-tight text-ink-950">
              TextileOps
            </span>
            <span className="hidden text-xs text-ink-400 sm:inline">Kaveri Knit Fabrics</span>
          </Link>
          <div className="ml-auto flex flex-1 items-center justify-end gap-3">
            <div className="hidden flex-1 justify-end md:flex">
              <GlobalSearch />
            </div>
            {user && (
              <div className="flex items-center gap-2">
                <span className="hidden text-right text-xs leading-tight sm:block">
                  <span className="block font-medium text-ink-800">{user.full_name}</span>
                  <span className="block text-ink-500">{user.role}</span>
                </span>
                <Button
                  variant="ghost"
                  onClick={() => {
                    clearSession();
                    router.replace("/login");
                  }}
                >
                  Sign out
                </Button>
              </div>
            )}
          </div>
        </div>
        <div className="px-4 pb-2 md:hidden">
          <GlobalSearch />
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1600px]">
        <aside
          className={`${
            navOpen ? "block" : "hidden"
          } w-full shrink-0 border-b border-ink-200 bg-white lg:sticky lg:top-[53px] lg:block lg:h-[calc(100vh-53px)] lg:w-56 lg:overflow-y-auto lg:border-b-0 lg:border-r`}
        >
          <SideNav onNavigate={() => setNavOpen(false)} />
        </aside>
        <main id="main" className="min-w-0 flex-1 px-4 py-5 lg:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}

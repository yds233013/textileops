"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { apiFetch, clearSession, getStoredUser, getToken } from "@/lib/api";
import { roleLabel } from "@/lib/labels";
import type { User } from "@/lib/types";
import { IconChevronDown, IconLogout, IconMenu, IconX, Logo } from "./icons";
import { SideNav, type NavCounts } from "./nav";
import { PilotModeBanner } from "./pilot";
import { GlobalSearch } from "./search";

/**
 * Content widths, chosen per route rather than per page so that no page can
 * forget. Dense operational tables get room; everything else stays composed.
 * On a 2560 px monitor a detail page is still 1320 px of readable content, not
 * a line of text that has to be followed across the whole screen.
 */
const WIDE = ["/orders", "/purchase-orders", "/inventory", "/production", "/quality", "/shipments", "/audit", "/exceptions"];
const NARROW = ["/settings", "/simulation", "/metrics"];

export function contentWidth(pathname: string): string {
  const isList = (prefix: string) => pathname === prefix;
  if (NARROW.some((p) => pathname.startsWith(p)) || pathname === "/proposals") return "max-w-narrow";
  if (WIDE.some(isList)) return "max-w-wide";
  return "max-w-page";
}

interface Health {
  demo_mode?: boolean;
  ai_provider?: string;
}

/** Application chrome. Redirects to the sign-in page when there is no session. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [counts, setCounts] = useState<NavCounts>({});
  const [health, setHealth] = useState<Health>({});

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

  // Badge counts: refreshed on navigation and every minute, so an approval
  // someone else just made does not linger as a number here.
  useEffect(() => {
    if (pathname === "/login" || !getToken()) return;
    let cancelled = false;
    const load = () =>
      apiFetch<NavCounts>("/system/counts")
        .then((value) => !cancelled && setCounts(value))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pathname]);

  useEffect(() => {
    if (pathname === "/login") return;
    apiFetch<Health>("/health").then(setHealth).catch(() => undefined);
  }, [pathname]);

  if (pathname === "/login") return <>{children}</>;
  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <Logo size={28} />
        <span className="sr-only">Checking your session…</span>
      </div>
    );
  }

  const signOut = () => {
    clearSession();
    router.replace("/login");
  };

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[60] focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:shadow-raised"
      >
        Skip to content
      </a>

      {/* Sidebar: pinned to the left edge at every width, full height. */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col bg-ink-950 lg:flex">
        <Brand />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <SideNav counts={counts} />
        </div>
        <SidebarFooter health={health} />
      </aside>

      {/* Mobile navigation */}
      {navOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/50" onClick={() => setNavOpen(false)} />
          <aside className="relative flex h-full w-72 flex-col bg-ink-950 shadow-overlay">
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <button
                type="button"
                aria-label="Close navigation"
                onClick={() => setNavOpen(false)}
                className="rounded-md p-1.5 text-ink-300 hover:bg-white/10"
              >
                <IconX />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <SideNav counts={counts} onNavigate={() => setNavOpen(false)} />
            </div>
            <SidebarFooter health={health} />
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <PilotModeBanner />
        <header className="sticky top-0 z-30 border-b border-ink-150 bg-white/90 backdrop-blur supports-[backdrop-filter]:bg-white/75">
          <div className="flex h-14 items-center gap-3 px-4 lg:px-8">
            <button
              type="button"
              aria-label="Open navigation"
              aria-expanded={navOpen}
              onClick={() => setNavOpen(true)}
              className="rounded-md p-1.5 text-ink-600 hover:bg-ink-100 lg:hidden"
            >
              <IconMenu size={18} />
            </button>
            <Link href="/" className="flex items-center gap-2 lg:hidden">
              <Logo size={22} />
              <span className="text-sm font-semibold text-ink-950">TextileOps</span>
            </Link>
            <div className="hidden min-w-0 max-w-md flex-1 md:block">
              <GlobalSearch />
            </div>
            <div className="ml-auto flex items-center gap-2.5">
              {health.demo_mode && (
                <span
                  title="Kaveri Knit Fabrics is a fictional company. Every order, supplier and figure here is invented demonstration data."
                  className="hidden items-center gap-1.5 rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-800 ring-1 ring-inset ring-brand-200 sm:inline-flex"
                >
                  <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-500" />
                  Demo · fictional data
                </span>
              )}
              {user && <UserMenu user={user} onSignOut={signOut} />}
            </div>
          </div>
          <div className="px-4 pb-2.5 md:hidden">
            <GlobalSearch />
          </div>
        </header>
        <main id="main" className={`mx-auto w-full px-4 py-6 lg:px-8 lg:py-7 ${contentWidth(pathname)}`}>
          {children}
        </main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex h-14 shrink-0 items-center gap-2.5 px-5">
      <Logo size={24} />
      <span className="leading-tight">
        <span className="block text-[14px] font-semibold tracking-tight text-white">TextileOps</span>
        <span className="block text-2xs text-ink-400">Kaveri Knit Fabrics</span>
      </span>
    </Link>
  );
}

function SidebarFooter({ health }: { health: Health }) {
  const live = health.ai_provider === "anthropic";
  return (
    <div className="border-t border-white/5 px-5 py-3 text-2xs leading-4 text-ink-500">
      <div className="flex items-center gap-1.5">
        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${live ? "bg-emerald-400" : "bg-ink-500"}`} />
        {health.ai_provider === undefined
          ? "Checking AI provider…"
          : live
            ? "AI: Claude (read-only)"
            : "AI: rule engine (no model)"}
      </div>
      <div className="mt-0.5">Models propose. People approve.</div>
    </div>
  );
}

function UserMenu({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const initials = user.full_name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-md py-1 pl-1 pr-1.5 hover:bg-ink-100"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-700 text-2xs font-semibold text-white">
          {initials}
        </span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block text-[13px] font-medium text-ink-900">{user.full_name}</span>
          <span className="block text-2xs text-ink-500">{roleLabel(user.role)}</span>
        </span>
        <IconChevronDown size={14} className="text-ink-400" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-1.5 w-56 rounded-lg bg-white p-1 shadow-overlay">
          <div className="border-b border-ink-100 px-2.5 py-2">
            <p className="truncate text-[13px] font-medium text-ink-900">{user.full_name}</p>
            <p className="truncate text-xs text-ink-500">{user.email}</p>
          </div>
          <Link
            role="menuitem"
            href="/settings"
            onClick={() => setOpen(false)}
            className="mt-1 block rounded-md px-2.5 py-1.5 text-[13px] text-ink-700 hover:bg-ink-50"
          >
            Settings
          </Link>
          <button
            role="menuitem"
            type="button"
            onClick={onSignOut}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ink-700 hover:bg-ink-50"
          >
            <IconLogout size={14} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

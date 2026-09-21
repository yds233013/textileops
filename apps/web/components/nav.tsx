"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType } from "react";
import {
  IconAlert,
  IconBuilding,
  IconChart,
  IconCheckCircle,
  IconClipboard,
  IconGauge,
  IconHistory,
  IconInbound,
  IconInbox,
  IconLayers,
  IconMerge,
  IconPlay,
  IconSettings,
  IconShield,
  IconSpool,
  IconStock,
  IconTruck,
} from "./icons";

export interface NavCounts {
  exceptions?: number;
  critical?: number;
  approvals?: number;
  reconciliation?: number;
}

interface Item {
  href: string;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  count?: keyof NavCounts;
  /** Paths that also count as this item being current. */
  match?: string[];
}

const SECTIONS: { title: string | null; items: Item[] }[] = [
  {
    title: null,
    items: [
      { href: "/", label: "Command centre", icon: IconGauge },
      { href: "/exceptions", label: "Exceptions", icon: IconAlert, count: "exceptions" },
      { href: "/proposals", label: "Approvals", icon: IconCheckCircle, count: "approvals" },
    ],
  },
  {
    title: "Orders",
    items: [
      { href: "/orders", label: "Customer orders", icon: IconClipboard },
      { href: "/shipments", label: "Shipments", icon: IconTruck },
    ],
  },
  {
    title: "Supply",
    items: [
      { href: "/purchase-orders", label: "Purchase orders", icon: IconInbound },
      { href: "/suppliers", label: "Suppliers", icon: IconBuilding },
      { href: "/inventory", label: "Inventory", icon: IconStock },
      { href: "/materials", label: "Materials & fabrics", icon: IconLayers },
    ],
  },
  {
    title: "Make",
    items: [
      { href: "/production", label: "Production", icon: IconSpool },
      { href: "/quality", label: "Quality", icon: IconShield },
    ],
  },
  {
    title: "Intake",
    items: [
      { href: "/documents", label: "Documents & messages", icon: IconInbox },
      { href: "/reconciliation", label: "Needs review", icon: IconMerge, count: "reconciliation" },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/audit", label: "Audit trail", icon: IconHistory },
      { href: "/metrics", label: "Product metrics", icon: IconChart },
      { href: "/simulation", label: "Simulation", icon: IconPlay },
      { href: "/settings", label: "Settings", icon: IconSettings },
    ],
  },
];

export function isActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function SideNav({
  onNavigate,
  counts = {},
}: {
  onNavigate?: () => void;
  counts?: NavCounts;
}) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="space-y-5 px-3 py-4">
      {SECTIONS.map((section, index) => (
        <div key={section.title ?? index}>
          {section.title && (
            <p className="px-2.5 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-ink-500">
              {section.title}
            </p>
          )}
          <ul className="space-y-px">
            {section.items.map((item) => {
              const active = isActive(item.href, pathname);
              const count = item.count ? counts[item.count] : undefined;
              const urgent = item.count === "exceptions" && (counts.critical ?? 0) > 0;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`group relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition ${
                      active
                        ? "bg-white/10 font-medium text-white"
                        : "text-ink-300 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {active && (
                      <span aria-hidden className="absolute -left-3 top-1.5 h-5 w-[3px] rounded-r bg-brand-300" />
                    )}
                    <item.icon
                      size={16}
                      className={active ? "text-brand-200" : "text-ink-400 group-hover:text-ink-200"}
                    />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {count !== undefined && count > 0 && (
                      <span
                        className={`rounded px-1.5 text-2xs font-semibold tnum ${
                          urgent
                            ? "bg-critical-solid text-white"
                            : item.count === "approvals"
                              ? "bg-brand-500 text-white"
                              : "bg-white/10 text-ink-200"
                        }`}
                        aria-label={`${count} ${item.label.toLowerCase()}`}
                      >
                        {count}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

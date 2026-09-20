"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SECTIONS: { title: string; items: { href: string; label: string }[] }[] = [
  {
    title: "Attention",
    items: [
      { href: "/", label: "Dashboard" },
      { href: "/exceptions", label: "Command centre" },
      { href: "/proposals", label: "Approvals" },
    ],
  },
  {
    title: "Demand",
    items: [
      { href: "/orders", label: "Customer orders" },
      { href: "/shipments", label: "Shipments" },
    ],
  },
  {
    title: "Supply",
    items: [
      { href: "/purchase-orders", label: "Purchase orders" },
      { href: "/suppliers", label: "Suppliers" },
      { href: "/inventory", label: "Inventory" },
      { href: "/materials", label: "Materials & fabrics" },
    ],
  },
  {
    title: "Make",
    items: [
      { href: "/production", label: "Production" },
      { href: "/quality", label: "Quality" },
    ],
  },
  {
    title: "Intake",
    items: [
      { href: "/documents", label: "Documents & messages" },
      { href: "/reconciliation", label: "Reconciliation queue" },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/audit", label: "Audit log" },
      { href: "/metrics", label: "Product metrics" },
      { href: "/simulation", label: "Simulation" },
      { href: "/settings", label: "Settings" },
    ],
  },
];

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="space-y-5 py-4">
      {SECTIONS.map((section) => (
        <div key={section.title}>
          <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-400">
            {section.title}
          </p>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded px-3 py-1.5 text-sm transition ${
                      active
                        ? "bg-ink-900 font-medium text-white"
                        : "text-ink-700 hover:bg-ink-100 hover:text-ink-900"
                    }`}
                  >
                    {item.label}
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

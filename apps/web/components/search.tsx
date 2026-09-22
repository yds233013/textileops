"use client";

import Link from "@/components/link";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { humanise } from "@/lib/format";
import type { SearchHit } from "@/lib/types";
import { IconSearch } from "./icons";

/** Global search: order number, PO, supplier, customer, material, batch, shipment. */
export function GlobalSearch() {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (term.trim().length < 2) {
      setHits([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      apiFetch<SearchHit[]>("/search", { query: { q: term }, signal: controller.signal })
        .then((results) => {
          setHits(results);
          setOpen(true);
        })
        .catch(() => setHits([]));
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [term]);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (container.current && !container.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div ref={container} className="relative w-full max-w-md">
      <label htmlFor="global-search" className="sr-only">
        Search orders, purchase orders, suppliers, materials, batches
      </label>
      <IconSearch
        size={15}
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400"
      />
      <input
        id="global-search"
        type="search"
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        onFocus={() => hits.length > 0 && setOpen(true)}
        onKeyDown={(event) => event.key === "Escape" && setOpen(false)}
        placeholder="Search orders, POs, suppliers, batches…"
        className="block h-8 w-full rounded-md border-0 bg-ink-50 pl-8 pr-3 text-[13px] text-ink-900 ring-1 ring-inset ring-ink-150 placeholder:text-ink-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        autoComplete="off"
      />
      {open && (
        <div className="absolute z-40 mt-1.5 w-full min-w-[22rem] overflow-hidden rounded-lg bg-white shadow-overlay">
          {hits.length === 0 ? (
            <p className="px-3 py-2 text-sm text-ink-500">
              Nothing matches “{term}”.
            </p>
          ) : (
            <ul className="max-h-80 divide-y divide-ink-100 overflow-y-auto">
              {hits.map((hit) => (
                <li key={`${hit.entity_type}-${hit.entity_id}`}>
                  <Link
                    href={hit.href}
                    onClick={() => {
                      setOpen(false);
                      setTerm("");
                    }}
                    className="block px-3 py-2 hover:bg-brand-50/60"
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink-900">
                        {hit.label}
                      </span>
                      <span className="shrink-0 text-2xs font-medium uppercase tracking-wide text-ink-400">
                        {humanise(hit.entity_type)}
                      </span>
                    </span>
                    <span className="block truncate text-xs text-ink-500">{hit.sublabel}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

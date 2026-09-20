"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { humanise } from "@/lib/format";
import type { SearchHit } from "@/lib/types";
import { inputClass } from "./ui";

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
      <input
        id="global-search"
        type="search"
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        onFocus={() => hits.length > 0 && setOpen(true)}
        onKeyDown={(event) => event.key === "Escape" && setOpen(false)}
        placeholder="Search SO-1003, PO-00002, a supplier, 40s yarn, B-1042…"
        className={inputClass}
        autoComplete="off"
      />
      {open && (
        <div className="absolute z-40 mt-1 w-full overflow-hidden rounded-md border border-ink-200 bg-white shadow-lg">
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
                    className="block px-3 py-2 hover:bg-ink-50"
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink-900">
                        {hit.label}
                      </span>
                      <span className="shrink-0 text-[11px] uppercase tracking-wide text-ink-400">
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

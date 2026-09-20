/**
 * Formatting helpers.
 *
 * Units are always shown next to the number, dates always in a form an
 * operator reads without translating, and an unavailable figure is shown as
 * unavailable rather than as zero.
 */

export function quantity(value: string | number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(numeric)) return String(value);
  const formatted = numeric.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: Number.isInteger(numeric) ? 0 : 3,
  });
  return unit ? `${formatted} ${unit}` : formatted;
}

const CURRENCY_SYMBOL: Record<string, string> = {
  INR: "₹",
  USD: "$",
  GBP: "£",
  EUR: "€",
};

export function money(
  value: string | number | null | undefined,
  currency?: string | null,
): string {
  if (value === null || value === undefined || value === "") return "Not available";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(numeric)) return String(value);
  const symbol = currency ? (CURRENCY_SYMBOL[currency] ?? `${currency} `) : "";
  return `${symbol}${numeric.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * A promised date, an expected date and a required-by date are *calendar*
 * dates, not instants. Parsing "2026-10-06" as UTC midnight and then comparing
 * it with the viewer's local day makes an order look a day late in one time
 * zone and on time in another, so date-only values are parsed in the viewer's
 * own calendar.
 */
function parseCalendarDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

export function date(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = parseCalendarDate(value) ?? new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeAge(hours: number): string {
  if (hours < 1) return "just now";
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function daysFromNow(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = parseCalendarDate(value) ?? new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const target = Date.UTC(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const today = new Date();
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - start) / 86_400_000);
}

export function dueText(value: string | null | undefined): string {
  const days = daysFromNow(value);
  if (days === null) return "—";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "1 day ago";
  return days > 0 ? `in ${days} days` : `${Math.abs(days)} days ago`;
}

/** "supplier_delay" → "Supplier delay" */
export function humanise(value: string | null | undefined): string {
  if (!value) return "—";
  const spaced = value.replace(/[_-]+/g, " ").toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function percent(value: number | string | null | undefined, digits = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(numeric)) return "—";
  return `${(numeric * 100).toFixed(digits)}%`;
}

export function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

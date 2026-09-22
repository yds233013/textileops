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
  // Fixed locale: the same figure must read the same on every screen.
  const formatted = numeric.toLocaleString("en-US", {
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
  return `${symbol}${numeric.toLocaleString("en-US", {
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

/**
 * An instant ("2026-09-21T22:45:00Z") shown on the business's clock. The server
 * counts every day — "late", "overdue", "promised in 5 days" — on the UTC
 * calendar (services/clock.py), so timestamps are shown on it too. Shown in the
 * viewer's own zone instead, "Order placed 28 Aug, 17:00" sat beside "Ordered
 * 29 Aug" for the same order.
 */
function onBusinessClock(value: string): Date {
  const instant = new Date(value);
  return new Date(
    instant.getUTCFullYear(),
    instant.getUTCMonth(),
    instant.getUTCDate(),
    instant.getUTCHours(),
    instant.getUTCMinutes(),
  );
}

/**
 * Day before month, always: "20 Sep 2026". Unambiguous in India, the UK and the
 * US alike, which "09/10/2026" is not — and a delivery date read the wrong way
 * round is a promise broken by formatting.
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Written by hand: locales disagree ("Sept", "sep.") and a table needs one form. */
function dayMonth(d: Date, withYear: boolean): string {
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return withYear ? `${base} ${d.getFullYear()}` : base;
}

export function date(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = parseCalendarDate(value) ?? onBusinessClock(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return dayMonth(parsed, true);
}

/** "20 Sep" this year, "20 Sep 2025" otherwise. For tables and dense rows. */
export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = parseCalendarDate(value) ?? onBusinessClock(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return dayMonth(parsed, parsed.getFullYear() !== businessToday().getFullYear());
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = onBusinessClock(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const time = `${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}`;
  return `${dayMonth(parsed, parsed.getFullYear() !== businessToday().getFullYear())}, ${time}`;
}

/** "4 min ago", "3 h ago", "2 days ago" — for when something happened. */
export function ago(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const minutes = Math.round((Date.now() - parsed.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function relativeAge(hours: number): string {
  if (hours < 1) return "just now";
  if (hours < 24) return `${Math.round(hours)} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/**
 * The business's "today", as the server counts it. Every "late", "overdue" and
 * "in 5 days" the API reports is counted from the server's date, so the screen
 * must count from the same one: a visitor whose own clock is already on another
 * day would otherwise see "3 days late" beside "2 days ago" for the same order.
 * Set once from /health by the shell; until then, the UTC date the server also uses.
 */
let businessDate: Date | null = null;

export function setBusinessDate(value: string | null | undefined): void {
  businessDate = (value && parseCalendarDate(value)) || null;
}

export function businessToday(): Date {
  if (businessDate) return new Date(businessDate);
  const now = new Date();
  return new Date(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
}

export function daysFromNow(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = parseCalendarDate(value) ?? onBusinessClock(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const target = Date.UTC(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const today = businessToday();
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

/** A plain number with grouping and no trailing zeros: 1942.500 → "1,942.5". */
export function num(value: string | number | null | undefined): string {
  return quantity(value);
}

export function plural(count: number, singular: string, pluralForm?: string): string {
  return `${count} ${count === 1 ? singular : (pluralForm ?? `${singular}s`)}`;
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

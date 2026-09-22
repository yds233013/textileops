import { afterEach, describe, expect, it } from "vitest";
import { businessToday, bytes, dateTime, daysFromNow, dueText, humanise, money, percent, quantity, shortDate, setBusinessDate } from "@/lib/format";

describe("quantity", () => {
  it("always shows the unit beside the number", () => {
    expect(quantity("1563.158", "kg")).toBe("1,563.158 kg");
    expect(quantity("9000", "yd")).toBe("9,000 yd");
  });

  it("never prints a bare dash as a zero", () => {
    expect(quantity(null, "kg")).toBe("—");
    expect(quantity(undefined)).toBe("—");
    expect(quantity("0", "m")).toBe("0 m");
  });

  it("keeps metres and yards visually distinct", () => {
    expect(quantity("10000", "m")).not.toBe(quantity("10000", "yd"));
  });
});

describe("money", () => {
  it("says a missing value is unavailable rather than showing zero", () => {
    expect(money(null, "INR")).toBe("Not available");
    expect(money(undefined)).toBe("Not available");
  });

  it("renders the right symbol per currency", () => {
    expect(money("1250.5", "INR")).toBe("₹1,250.50");
    expect(money("1250.5", "GBP")).toBe("£1,250.50");
    expect(money("1250.5", "USD")).toBe("$1,250.50");
  });
});

describe("dueText", () => {
  /** A calendar date N days from the business's today. */
  const isoDaysFromNow = (days: number) => {
    setBusinessDate("2026-09-22");
    const date = businessToday();
    date.setDate(date.getDate() + days);
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
  };

  it("reads the way an operator speaks", () => {
    expect(dueText(isoDaysFromNow(0))).toBe("today");
    expect(dueText(isoDaysFromNow(1))).toBe("tomorrow");
    expect(dueText(isoDaysFromNow(5))).toBe("in 5 days");
    expect(dueText(isoDaysFromNow(-3))).toBe("3 days ago");
  });
});

describe("humanise", () => {
  it("turns enum values into prose", () => {
    expect(humanise("supplier_delay")).toBe("Supplier delay");
    expect(humanise("MATERIAL_SHORTAGE")).toBe("Material shortage");
    expect(humanise(null)).toBe("—");
  });
});

describe("percent and bytes", () => {
  it("formats ratios and sizes", () => {
    expect(percent(0.72)).toBe("72%");
    expect(percent(null)).toBe("—");
    expect(bytes(2048)).toBe("2.0 KB");
  });
});

describe("business date", () => {
  afterEach(() => setBusinessDate(null));

  it("counts every relative date from the server's today, not the browser's", () => {
    // A visitor whose clock is still on the 21st, looking at a business already
    // on the 22nd, once saw "3 days late" beside "2 days ago" for one order.
    setBusinessDate("2026-09-22");
    expect(daysFromNow("2026-09-19")).toBe(-3);
    expect(dueText("2026-09-19")).toBe("3 days ago");
    expect(dueText("2026-09-23")).toBe("tomorrow");
    expect(businessToday().getDate()).toBe(22);
  });

  it("falls back to the UTC date, which is the server's, until the server has said", () => {
    setBusinessDate(null);
    expect(businessToday().getDate()).toBe(new Date().getUTCDate());
  });
});

describe("timestamps", () => {
  it("are shown on the business clock, the same one every date is counted on", () => {
    // Just after midnight UTC on the 29th is still the 28th in California; the
    // order date beside it says the 29th, and so must this.
    expect(dateTime("2026-08-29T00:30:00Z")).toBe("29 Aug, 00:30");
    expect(shortDate("2026-08-29T00:30:00Z")).toBe("29 Aug");
  });
});

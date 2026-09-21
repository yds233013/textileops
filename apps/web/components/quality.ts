import type { Tone } from "./ui";
import type { Measurement } from "@/lib/types";

/**
 * One measurement, stated no more strongly than it was taken. A value against
 * a numeric band is in or out of tolerance. A visual judgement with no band is
 * the inspector's call — shown with their words, never as "passed" and never
 * as "not assessed" when it plainly was. No reading at all is "not measured",
 * which is never treated as a pass.
 */
export function measurementVerdict(m: Measurement): { label: string; tone: Tone } {
  if (m.result === "out_of_tolerance") return { label: "Out of tolerance", tone: "bad" };
  if (m.result === "within_tolerance") return { label: "Within tolerance", tone: "ok" };
  if (m.observed_text || m.observed_value) return { label: "Inspector's judgement", tone: "info" };
  return { label: "Not measured", tone: "neutral" };
}

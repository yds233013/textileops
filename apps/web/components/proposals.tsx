import type { Proposal } from "@/lib/types";

/** Where a proposal came from, in words — and never "AI" when no model was involved. */
export function originText(proposal: Proposal): string {
  if (proposal.origin === "human") return proposal.created_by_name ? `Raised by ${proposal.created_by_name}` : "Raised by a person";
  if (proposal.origin === "ai_investigation") return proposal.model === "deterministic-rules-v1" || !proposal.model ? "From an investigation (rule engine)" : "From an AI investigation";
  return "From the rule engine";
}

"use client";

import { useApi } from "@/lib/hooks";
import type { Settings } from "@/lib/types";

/**
 * Says so, plainly, when TextileOps is not changing anything by itself.
 *
 * This banner is a *report* of the server's setting, never the thing that
 * enforces it — enforcement lives in the services, because a mode that can be
 * stepped around with a curl command is a label rather than a control. The
 * banner exists so that an operator reading a screen knows why a supplier's
 * date change is sitting in the reconciliation queue instead of having
 * happened.
 */
export function PilotModeBanner() {
  const settings = useApi<Settings>("/settings");
  if (!settings.data?.pilot_mode) return null;

  return (
    <div
      role="status"
      className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900"
    >
      <span className="font-semibold">Pilot mode.</span>{" "}
      {settings.data.pilot_mode_note}
    </div>
  );
}

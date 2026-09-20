"use client";

import {
  Badge,
  Card,
  DefinitionList,
  ErrorState,
  Loading,
  PageHeader,
} from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Settings } from "@/lib/types";

export default function SettingsPage() {
  const { data, error, loading, reload } = useApi<Settings>("/settings");

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title="Settings"
        description="What is configured, and — just as importantly — what is not."
      />

      <Card
        title="Integrations"
        subtitle="TextileOps never claims a connection it does not have."
        className="mb-4"
      >
        <ul className="space-y-3">
          {data.integrations.map((integration) => (
            <li
              key={integration.key}
              className="rounded border border-ink-200 p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-ink-900">{integration.name}</span>
                <Badge tone={integration.configured ? "ok" : "neutral"}>
                  {integration.configured ? "Connected" : "Not configured"}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-ink-600">{integration.detail}</p>
            </li>
          ))}
        </ul>
      </Card>

      <Card
        title="Business thresholds"
        subtitle="These decide when TextileOps starts worrying. Change them in the environment."
        className="mb-4"
      >
        <DefinitionList
          items={[
            {
              term: "Order risk buffer",
              value: `${data.order_at_risk_buffer_days} days`,
              hint: "Below this much slack an order is put on watch.",
            },
            {
              term: "Supplier delay threshold",
              value: `${data.supplier_delay_warn_days} days`,
              hint: "A revised ETA beyond this is raised as a supplier delay.",
            },
            {
              term: "Shipment delivery grace",
              value: `${data.shipment_delay_grace_days} days`,
              hint: "Allowed slack before an undelivered shipment is flagged.",
            },
            { term: "Environment", value: data.environment },
            {
              term: "Simulation",
              value: data.simulation_enabled ? "Enabled" : "Disabled",
              hint: "Never available in production.",
            },
          ]}
        />
      </Card>

      <Card title="Uploads and workers">
        <DefinitionList
          items={[
            { term: "Maximum upload size", value: `${data.max_upload_mb} MB` },
            {
              term: "Accepted file types",
              value: data.allowed_upload_extensions.join(", "),
            },
            { term: "Background tasks", value: data.worker_tasks.join(", ") },
          ]}
        />
      </Card>
    </>
  );
}

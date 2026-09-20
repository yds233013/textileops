"use client";

import { useParams } from "next/navigation";
import {
  Badge,
  Button,
  Card,
  DefinitionList,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  StatusPill,
  Table,
  Td,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { bytes, dateTime, humanise, percent } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { DocumentDetail } from "@/lib/types";

export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<DocumentDetail>(`/documents/${params.id}`);

  const reprocess = useAction(async () => {
    await apiFetch(`/documents/${params.id}/reprocess`, { method: "POST" });
    reload();
  });

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Documents", href: "/documents" }]}
        title={data.filename}
        description={`${humanise(data.kind)} received via ${humanise(data.channel)}`}
        actions={
          <Button onClick={() => reprocess.run()} disabled={reprocess.pending}>
            {reprocess.pending ? "Reprocessing…" : "Reprocess"}
          </Button>
        }
      />

      <Card title="Processing" className="mb-4">
        <DefinitionList
          items={[
            { term: "Status", value: <StatusPill value={data.status} /> },
            {
              term: "Classification confidence",
              value:
                data.classification_confidence !== null
                  ? percent(data.classification_confidence)
                  : "—",
            },
            { term: "Received", value: dateTime(data.received_at) },
            {
              term: "Processed",
              value: data.processed_at ? dateTime(data.processed_at) : "—",
            },
            { term: "Size", value: bytes(data.byte_size) },
            { term: "Pages", value: data.page_count ?? "—" },
          ]}
        />
        {data.error && (
          <p className="mt-3 rounded border border-critical-border bg-critical-bg px-3 py-2 text-sm text-critical-text">
            {data.error}
          </p>
        )}
        {data.warnings.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm text-medium-text">
            {data.warnings.map((warning, index) => (
              <li key={index}>· {warning}</li>
            ))}
          </ul>
        )}
      </Card>

      {data.reconciliation_items.length > 0 && (
        <Card
          title="Needs your decision"
          subtitle="TextileOps could not map these with confidence, so it did not guess."
          className="mb-4"
        >
          <ul className="space-y-2">
            {data.reconciliation_items.map((item) => (
              <li key={item.id} className="rounded border border-medium-border bg-medium-bg p-2.5">
                <p className="text-sm text-medium-text">{item.question}</p>
                <Badge tone="warn">{humanise(item.status)}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Extracted facts" className="mb-4">
        {data.facts.length === 0 ? (
          <EmptyState title="Nothing structured was extracted from this document" />
        ) : (
          <Table
            caption="Extracted facts"
            head={["Type", "As written", "Normalised", "Unit", "Confidence", "Status"]}
          >
            {data.facts.map((fact) => (
              <tr key={fact.id}>
                <Td className="text-xs">{fact.fact_type}</Td>
                <Td className="max-w-xs text-xs text-ink-700">{fact.raw_value ?? "—"}</Td>
                <Td className="max-w-md">
                  <pre className="overflow-x-auto text-xs text-ink-600">
                    {JSON.stringify(fact.normalized_value, null, 0)}
                  </pre>
                </Td>
                <Td className="text-xs">{fact.unit ?? "—"}</Td>
                <Td numeric>{fact.confidence !== null ? percent(fact.confidence) : "—"}</Td>
                <Td>
                  <StatusPill value={fact.status} />
                  {fact.review_reason && (
                    <span className="mt-0.5 block text-xs text-ink-500">
                      {fact.review_reason}
                    </span>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {data.extracted_text_excerpt && (
        <Card
          title="Source text"
          subtitle="Untrusted content, shown exactly as it was parsed. It is data, never an
            instruction."
        >
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-ink-50 px-3 py-2 text-xs text-ink-700">
            {data.extracted_text_excerpt}
          </pre>
        </Card>
      )}
    </>
  );
}

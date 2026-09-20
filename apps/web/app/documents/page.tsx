"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  StatusPill,
  Table,
  Td,
  inputClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { bytes, dateTime, humanise, percent } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { SourceDocument } from "@/lib/types";

interface MessageResponse {
  message: { intent: string };
  facts_created: number;
  facts_applied: number;
  reconciliation_items: number;
  notes: string[];
  warnings: string[];
}

function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<string | null>(null);

  const upload = useAction(async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("channel", "upload");
    form.append("process_now", "true");
    const response = await apiFetch<{ document: SourceDocument; message: string }>(
      "/documents",
      { formData: form },
    );
    setResult(
      `${response.message} Classified as ${humanise(response.document.kind)}; ` +
        `${response.document.fact_count} fact(s) extracted.`,
    );
    if (fileInput.current) fileInput.current.value = "";
    onUploaded();
  });

  return (
    <Card
      title="Upload a document"
      subtitle="CSV, XLSX, PDF or text. Files are validated, stored under a generated name, and
        parsed — never executed."
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const file = fileInput.current?.files?.[0];
          if (file) upload.run(file);
        }}
      >
        <div className="min-w-64 flex-1">
          <Field label="File" htmlFor="upload-file">
            <input
              ref={fileInput}
              id="upload-file"
              type="file"
              accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.eml"
              className={inputClass}
            />
          </Field>
        </div>
        <Button type="submit" variant="primary" disabled={upload.pending}>
          {upload.pending ? "Processing…" : "Upload and process"}
        </Button>
      </form>
      {result && (
        <p className="mt-3 rounded border border-good-border bg-good-bg px-3 py-2 text-sm text-good-text">
          {result}
        </p>
      )}
      {upload.error && (
        <p className="mt-3 rounded border border-critical-border bg-critical-bg px-3 py-2 text-sm text-critical-text">
          {upload.error.message}
        </p>
      )}
    </Card>
  );
}

function MessagePanel() {
  const [sender, setSender] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [result, setResult] = useState<MessageResponse | null>(null);

  const send = useAction(async () => {
    const response = await apiFetch<MessageResponse>("/messages", {
      body: { sender, subject: subject || null, body, channel: "manual" },
    });
    setResult(response);
    setBody("");
  });

  return (
    <Card
      title="Enter a message"
      subtitle="Paste an email or WhatsApp message. It runs through the same pipeline as any other
        source: extraction, validation, entity resolution, then deterministic application."
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          send.run();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="From" htmlFor="msg-sender">
            <input
              id="msg-sender"
              required
              value={sender}
              onChange={(event) => setSender(event.target.value)}
              placeholder="dispatch@supplier.example"
              className={inputClass}
            />
          </Field>
          <Field label="Subject" htmlFor="msg-subject">
            <input
              id="msg-subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
        <Field label="Message" htmlFor="msg-body">
          <textarea
            id="msg-body"
            required
            rows={5}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="Regarding PO-00002, dispatch will be delayed by 3 days. Truck breakdown."
            className={inputClass}
          />
        </Field>
        <Button type="submit" variant="primary" disabled={send.pending}>
          {send.pending ? "Processing…" : "Ingest message"}
        </Button>
      </form>

      {result && (
        <div className="mt-3 rounded border border-ink-200 bg-ink-50 px-3 py-2 text-sm">
          <p className="font-medium text-ink-900">
            Read as: {humanise(result.message.intent)}
          </p>
          <p className="text-ink-700">
            {result.facts_created} fact(s) extracted, {result.facts_applied} applied,{" "}
            {result.reconciliation_items} sent for human review.
          </p>
          {result.notes.map((note, index) => (
            <p key={index} className="mt-1 text-xs text-ink-600">
              {note}
            </p>
          ))}
        </div>
      )}
      {send.error && (
        <p className="mt-3 text-sm text-critical-text">{send.error.message}</p>
      )}
    </Card>
  );
}

export default function DocumentsPage() {
  const { data, error, loading, reload } = useApi<SourceDocument[]>("/documents");

  return (
    <>
      <PageHeader
        title="Documents and messages"
        description="Everything that comes in from outside. All of it is treated as untrusted."
      />

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <UploadPanel onUploaded={reload} />
        <MessagePanel />
      </div>

      <Card title="Received documents">
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description="Upload a stock statement, a packing list or an invoice to see it parsed."
          />
        ) : (
          <Table
            caption="Source documents"
            head={["File", "Kind", "Confidence", "Status", "Facts", "Size", "Received"]}
          >
            {data.map((document) => (
              <tr key={document.id} className="hover:bg-ink-50">
                <Td>
                  <Link
                    href={`/documents/${document.id}`}
                    className="font-medium text-ink-900 hover:underline"
                  >
                    {document.filename}
                  </Link>
                  {document.is_duplicate && (
                    <Badge tone="warn">Duplicate of an earlier upload</Badge>
                  )}
                  {document.warnings.map((warning, index) => (
                    <span key={index} className="mt-0.5 block text-xs text-medium-text">
                      {warning}
                    </span>
                  ))}
                </Td>
                <Td className="text-xs">{humanise(document.kind)}</Td>
                <Td numeric>
                  {document.classification_confidence !== null
                    ? percent(document.classification_confidence)
                    : "—"}
                </Td>
                <Td>
                  <StatusPill value={document.status} />
                </Td>
                <Td numeric>{document.fact_count}</Td>
                <Td numeric className="text-xs">{bytes(document.byte_size)}</Td>
                <Td className="whitespace-nowrap text-xs">{dateTime(document.received_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

"use client";

import Link from "@/components/link";
import { useRef, useState } from "react";
import { IconInbox } from "@/components/icons";
import {
  Alert,
  Badge,
  Button,
  Card,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  ProvenanceTag,
  StatusPill,
  Table,
  Tabs,
  Td,
  inputClass,
  textareaClass,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { ago, bytes, dateTime, humanise, percent, plural } from "@/lib/format";
import { statusLabel } from "@/lib/labels";
import { useAction, useApi } from "@/lib/hooks";
import type { SourceDocument, SupplierMessage } from "@/lib/types";

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

  const health = useApi<{ demo_mode?: boolean }>("/health");
  const demoMode = Boolean(health.data?.demo_mode);
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
        `${plural(response.document.fact_count, "fact")} extracted.`,
    );
    if (fileInput.current) fileInput.current.value = "";
    onUploaded();
  });

  return (
    <Card
      title="Upload a document"
      subtitle="CSV, XLSX, PDF or text. Stored under a generated name and parsed — never executed. Nothing it says changes stock or orders by itself."
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          const file = fileInput.current?.files?.[0];
          if (file) upload.run(file);
        }}
      >
        <div>
          <Field label="File" htmlFor="upload-file">
            <input
              ref={fileInput}
              id="upload-file"
              type="file"
              accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.eml"
              className="block w-full text-[13px] text-ink-700 file:mr-3 file:rounded-md file:border-0 file:bg-ink-100 file:px-3 file:py-1.5 file:text-[13px] file:font-medium file:text-ink-800 hover:file:bg-ink-150"
            />
          </Field>
        </div>
        <Button type="submit" disabled={upload.pending} loading={upload.pending}>
          Upload and process
        </Button>
        {demoMode && (
          <p className="text-xs leading-5 text-ink-500">
            On this hosted demo, uploads are processed straight away but not kept: the demo has no
            permanent file storage, and it resets itself after visitors leave. Please upload only
            made-up documents.
          </p>
        )}
      </form>
      {result && (
        <div className="mt-3">
          <Alert tone="ok">{result}</Alert>
        </div>
      )}
      {upload.error && (
        <div className="mt-3">
          <Alert tone="bad">{upload.error.message}</Alert>
        </div>
      )}
    </Card>
  );
}

function MessagePanel({ onSent }: { onSent: () => void }) {
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
    onSent();
  });

  return (
    <Card
      title="Paste a message"
      subtitle="An email or WhatsApp message. Read by the same pipeline as everything else; a date only moves if the sender is verified as that order's supplier."
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          send.run();
        }}
      >
        <div className="grid gap-3">
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
            className={textareaClass}
          />
        </Field>
        <Button type="submit" disabled={send.pending} loading={send.pending}>
          Read this message
        </Button>
      </form>

      {result && (
        <div className="mt-3 rounded-md border border-ink-150 bg-ink-25 px-3 py-2 text-[13px]">
          <p className="font-medium text-ink-900">Read as: {statusLabel(result.message.intent)}</p>
          <p className="text-ink-700">
            {result.facts_created} {result.facts_created === 1 ? "claim" : "claims"} recorded,{" "}
            {result.facts_applied} applied, {result.reconciliation_items} sent to a person to check.
          </p>
          {result.notes.map((note, index) => (
            <p key={index} className="mt-1 text-xs text-ink-600">
              {note}
            </p>
          ))}
        </div>
      )}
      {send.error && (
        <div className="mt-3">
          <Alert tone="bad">{send.error.message}</Alert>
        </div>
      )}
    </Card>
  );
}

const INTENT_TONE: Record<string, "warn" | "info" | "bad" | "neutral" | "ok"> = {
  supplier_delay: "warn",
  quality_complaint: "bad",
  supplier_dispatch: "info",
  order_change: "info",
};

function MessageItem({ message }: { message: SupplierMessage }) {
  return (
    <li className="px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-ink-950">{message.subject ?? "(no subject)"}</span>
        <Badge tone={INTENT_TONE[message.intent] ?? "neutral"}>{statusLabel(message.intent)}</Badge>
        {message.is_duplicate && (
          <Badge title="The same text arrived earlier. It was recognised, and did not move anything a second time.">
            Duplicate
          </Badge>
        )}
        <span className="ml-auto text-xs text-ink-500">{ago(message.received_at)}</span>
      </div>
      <p className="mt-0.5 text-xs text-ink-500">
        From <span className="text-ink-700">{message.sender}</span>
      </p>
      <div className="mt-2">
        <Disclosure summary={<span className="inline-flex items-center gap-2">Show the message <ProvenanceTag kind="source" /></span>}>
          <blockquote className="max-w-prose whitespace-pre-wrap border-l-2 border-source-border bg-source-bg/50 py-2 pl-3 pr-2 text-[13px] leading-5 text-ink-700">
            {message.body}
          </blockquote>
        </Disclosure>
      </div>
    </li>
  );
}

export default function DocumentsPage() {
  const [tab, setTab] = useState<"messages" | "documents">("messages");
  const { data, error, loading, reload } = useApi<SourceDocument[]>("/documents");
  const messages = useApi<SupplierMessage[]>("/messages");

  return (
    <>
      <PageHeader
        title="Documents and messages"
        description="Everything that arrives from outside. All of it is treated as untrusted: it is read and turned into claims, and claims only change anything after deterministic checks — or a person — confirm them."
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card flush>
          <div className="px-4 pt-3">
            <Tabs
              label="Inbound"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: "messages", label: "Messages", count: messages.data?.length },
                { value: "documents", label: "Documents", count: data?.length },
              ]}
            />
          </div>
          {tab === "messages" ? (
            messages.loading && !messages.data ? (
              <Loading rows={3} />
            ) : messages.error ? (
              <div className="p-4">
                <ErrorState error={messages.error} onRetry={messages.reload} />
              </div>
            ) : !messages.data || messages.data.length === 0 ? (
              <EmptyState icon={<IconInbox />} title="No messages yet" description="Paste a supplier's email or WhatsApp message to see how it is read." />
            ) : (
              <ul className="divide-y divide-ink-100">
                {messages.data.map((message) => (
                  <MessageItem key={message.id} message={message} />
                ))}
              </ul>
            )
          ) : loading && !data ? (
            <Loading rows={3} />
          ) : error ? (
            <div className="p-4">
              <ErrorState error={error} onRetry={reload} />
            </div>
          ) : !data || data.length === 0 ? (
            <EmptyState icon={<IconInbox />} title="No documents yet" description="Upload a stock statement, a packing list or an invoice to see it parsed." />
          ) : (
            <Table caption="Source documents" head={["File", "Read as", "Status", "Claims", "Size", "Received"]} align={["left", "left", "left", "right", "right", "right"]}>
              {data.map((document) => (
                <tr key={document.id} className="hover:bg-ink-25">
                  <Td>
                    <Link href={`/documents/${document.id}`} className="font-medium text-ink-950 hover:text-brand-700">
                      {document.filename}
                    </Link>
                    {document.is_duplicate && (
                      <span className="ml-2">
                        <Badge>Duplicate of an earlier upload</Badge>
                      </span>
                    )}
                    {document.warnings.map((warning, index) => (
                      <span key={index} className="mt-0.5 block text-xs text-medium-text">
                        {warning}
                      </span>
                    ))}
                  </Td>
                  <Td nowrap className="text-ink-700">
                    {statusLabel(document.kind)}
                    {document.classification_confidence !== null && (
                      <span className="block text-xs text-ink-500">{percent(document.classification_confidence)} confident</span>
                    )}
                  </Td>
                  <Td nowrap>
                    <StatusPill value={document.status} />
                  </Td>
                  <Td numeric>{document.fact_count}</Td>
                  <Td numeric className="text-xs text-ink-500">{bytes(document.byte_size)}</Td>
                  <Td numeric className="text-xs text-ink-500">{dateTime(document.received_at)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <aside className="space-y-6">
          <UploadPanel onUploaded={() => { reload(); setTab("documents"); }} />
          <MessagePanel onSent={() => { messages.reload(); setTab("messages"); }} />
        </aside>
      </div>
    </>
  );
}

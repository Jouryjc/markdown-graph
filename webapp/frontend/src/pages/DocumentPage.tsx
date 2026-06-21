// Document detail view: sidebar of all documents + main pane showing the
// selected document's path, frontmatter, chunks, and out-links.
import { Link, useParams } from "react-router-dom";
import {
  AlertCircle,
  FileText,
  Link2,
  Loader2,
} from "lucide-react";

import { useDocument, useDocuments } from "../api/hooks";
import { ApiError } from "../api/client";
import type {
  DocumentChunk,
  DocumentDetail,
  DocumentSummary,
} from "../api/types";

// --- sidebar listing all documents -----------------------------------------

interface DocumentSidebarProps {
  documents: DocumentSummary[] | undefined;
  isLoading: boolean;
  isError: boolean;
  selectedId: string | undefined;
}

function DocumentSidebar({
  documents,
  isLoading,
  isError,
  selectedId,
}: DocumentSidebarProps) {
  return (
    <aside className="w-64 shrink-0 border-r border-gray-200 bg-gray-50">
      <div className="border-b border-gray-200 px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
          Documents
        </h2>
      </div>
      <nav className="overflow-y-auto p-2">
        {isLoading && (
          <div className="flex items-center gap-2 px-2 py-3 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading…
          </div>
        )}
        {isError && (
          <div className="px-2 py-3 text-sm text-red-600">
            Failed to load documents.
          </div>
        )}
        {!isLoading && !isError && documents && documents.length === 0 && (
          <div className="px-2 py-3 text-sm text-gray-500">
            No documents indexed yet.
          </div>
        )}
        {!isLoading &&
          !isError &&
          documents?.map((doc) => {
            const active = doc.id === selectedId;
            return (
              <Link
                key={doc.id}
                to={`/doc/${encodeURIComponent(doc.id)}`}
                className={[
                  "flex items-start gap-2 rounded-md px-2 py-2 text-sm",
                  active
                    ? "bg-blue-100 text-blue-800"
                    : "text-gray-700 hover:bg-gray-100",
                ].join(" ")}
                aria-current={active ? "page" : undefined}
                title={doc.path}
              >
                <FileText className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{doc.path}</span>
                  <span className="block text-xs text-gray-400">
                    {doc.chunk_count} chunk{doc.chunk_count === 1 ? "" : "s"}
                  </span>
                </span>
              </Link>
            );
          })}
      </nav>
    </aside>
  );
}

// --- frontmatter rendering --------------------------------------------------

function formatFrontmatterValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function Frontmatter({
  frontmatter,
}: {
  frontmatter: Record<string, unknown>;
}) {
  const entries = Object.entries(frontmatter);
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="font-medium text-gray-500">{key}</dt>
          <dd className="break-words text-gray-800">
            {formatFrontmatterValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// --- chunk rendering --------------------------------------------------------

function HeadingBreadcrumb({ sectionPath }: { sectionPath: string }) {
  const parts = sectionPath
    .split(/[>/]/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <div className="mb-1 flex flex-wrap items-center gap-1 text-xs text-gray-400">
      {parts.map((part, i) => (
        <span key={`${part}-${i}`} className="flex items-center gap-1">
          {i > 0 && <span aria-hidden>›</span>}
          <span>{part}</span>
        </span>
      ))}
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: DocumentChunk }) {
  return (
    <article className="rounded-md border border-gray-200 p-4">
      <HeadingBreadcrumb sectionPath={chunk.section_path} />
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-800">
        {chunk.text}
      </p>
    </article>
  );
}

// --- out-links --------------------------------------------------------------

function OutLinks({ links }: { links: string[] }) {
  if (links.length === 0) return null;
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        <Link2 className="h-4 w-4" aria-hidden />
        Links to
      </h2>
      <ul className="flex flex-wrap gap-2">
        {links.map((linkedId) => (
          <li key={linkedId}>
            <Link
              to={`/doc/${encodeURIComponent(linkedId)}`}
              className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm text-blue-700 hover:bg-blue-100"
            >
              {linkedId}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --- main detail pane -------------------------------------------------------

function DocumentDetailView({ detail }: { detail: DocumentDetail }) {
  const { document, chunks, links } = detail;
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold text-gray-900">
          <FileText className="h-5 w-5 text-blue-600" aria-hidden />
          {document.path}
        </h1>
        <p className="text-xs text-gray-400">id: {document.id}</p>
      </header>

      <Frontmatter frontmatter={document.frontmatter} />

      <OutLinks links={links} />

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
          Chunks ({chunks.length})
        </h2>
        {chunks.length === 0 ? (
          <p className="text-sm text-gray-500">This document has no chunks.</p>
        ) : (
          <div className="space-y-3">
            {chunks.map((chunk) => (
              <ChunkCard key={chunk.id} chunk={chunk} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// --- page -------------------------------------------------------------------

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  const docId = id ?? null;

  const documentsQuery = useDocuments();
  const detailQuery = useDocument(docId);

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <DocumentSidebar
        documents={documentsQuery.data}
        isLoading={documentsQuery.isLoading}
        isError={documentsQuery.isError}
        selectedId={docId ?? undefined}
      />

      <main className="flex-1 overflow-y-auto p-6">
        {docId == null && (
          <div className="flex h-full items-center justify-center text-center text-gray-500">
            <div>
              <FileText
                className="mx-auto mb-2 h-8 w-8 text-gray-300"
                aria-hidden
              />
              <p>Pick a document from the sidebar to view its contents.</p>
            </div>
          </div>
        )}

        {docId != null && detailQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading document…
          </div>
        )}

        {docId != null && detailQuery.isError && (
          <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div>
              <p className="font-medium">
                {detailQuery.error instanceof ApiError &&
                detailQuery.error.status === 404
                  ? `Document "${docId}" was not found.`
                  : "Failed to load document."}
              </p>
              {detailQuery.error instanceof Error && (
                <p className="mt-1 text-xs text-red-500">
                  {detailQuery.error.message}
                </p>
              )}
            </div>
          </div>
        )}

        {docId != null && detailQuery.isSuccess && detailQuery.data && (
          <DocumentDetailView detail={detailQuery.data} />
        )}
      </main>
    </div>
  );
}

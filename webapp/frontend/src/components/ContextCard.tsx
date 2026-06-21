import { Sparkles } from "lucide-react";

import type { Context } from "../api/types";

export interface ContextCardProps {
  context: Context;
  /**
   * Optional: open the source document. Passed the context's `doc_id` (the
   * document NODE id the backend route keys on), NOT the human-readable
   * source_path. Disabled when the context carries no doc_id.
   */
  onOpenDocument?: (docId: string) => void;
}

function formatScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(3) : "—";
}

/**
 * Presentational retrieval-result card. No data fetching — fully unit-testable.
 *
 * Shows the formatted score, the source path (clickable when `onOpenDocument`
 * is supplied), a heading-path breadcrumb, a clamped text snippet, and a small
 * "图扩展" badge when the hit was brought in by graph expansion
 * (`context.from_graph === true`).
 */
export default function ContextCard({
  context,
  onOpenDocument,
}: ContextCardProps) {
  const crumbs = context.heading_path
    .split(/\s*>\s*|\//)
    .map((c) => c.trim())
    .filter((c) => c.length > 0);

  return (
    <article className="rounded border border-gray-200 bg-white p-3 shadow-sm">
      <header className="mb-1.5 flex items-center justify-between gap-2">
        <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-600">
          {formatScore(context.score)}
        </span>
        {context.from_graph && (
          <span className="inline-flex items-center gap-1 rounded bg-purple-100 px-1.5 py-0.5 text-xs font-medium text-purple-700">
            <Sparkles size={12} />
            图扩展
          </span>
        )}
      </header>

      {onOpenDocument && context.doc_id ? (
        <button
          type="button"
          onClick={() => onOpenDocument(context.doc_id)}
          className="block max-w-full truncate text-left text-xs font-medium text-blue-600 hover:underline"
          title={context.source_path}
        >
          {context.source_path}
        </button>
      ) : (
        <div
          className="truncate text-xs font-medium text-gray-500"
          title={context.source_path}
        >
          {context.source_path}
        </div>
      )}

      {crumbs.length > 0 && (
        <nav
          aria-label="heading path"
          className="mt-0.5 flex flex-wrap items-center gap-1 text-xs text-gray-400"
        >
          {crumbs.map((crumb, i) => (
            <span key={`${i}:${crumb}`} className="flex items-center gap-1">
              {i > 0 && <span aria-hidden>›</span>}
              <span>{crumb}</span>
            </span>
          ))}
        </nav>
      )}

      <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm text-gray-800">
        {context.text}
      </p>
    </article>
  );
}

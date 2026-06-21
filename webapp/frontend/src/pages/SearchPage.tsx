import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";

import { ApiError } from "../api/client";
import { useQuerySearch } from "../api/hooks";
import type { QueryRequest } from "../api/types";
import ContextCard from "../components/ContextCard";
import RetrievalControls, {
  type RetrievalControlsValue,
} from "../components/RetrievalControls";
import SubgraphPanel from "../components/SubgraphPanel";

const DEFAULT_CONTROLS: RetrievalControlsValue = {
  k: 8,
  mode: "dual",
  graph_weight: 0.5,
  per_doc_cap: 2,
  hops: 2,
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "检索失败，请稍后重试。";
}

/**
 * Dual / vector retrieval page. A query box + RetrievalControls drive a
 * POST /api/query mutation; results render as ContextCards on the left and the
 * returned subgraph on the right (wide screens). Loading / error / empty states
 * are all handled explicitly. Strictly typed; no `any`.
 */
export default function SearchPage() {
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [controls, setControls] =
    useState<RetrievalControlsValue>(DEFAULT_CONTROLS);

  const search = useQuerySearch();
  const { data, isPending, isError, error, isSuccess } = search;

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length === 0) return;

    const body: QueryRequest = {
      query: trimmed,
      k: controls.k,
      mode: controls.mode,
      graph_weight: controls.graph_weight,
      per_doc_cap: controls.per_doc_cap,
      hops: controls.hops,
    };
    search.mutate(body);
  };

  const openDocument = (docId: string) => {
    navigate(`/doc/${encodeURIComponent(docId)}`);
  };

  const contexts = data?.contexts ?? [];
  const subgraph = data?.subgraph ?? null;
  const showEmpty = isSuccess && contexts.length === 0;

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Search</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* main column: query form + results */}
        <div className="min-w-0 space-y-4 lg:order-1">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="search"
              aria-label="Query"
              placeholder="Ask a question…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={isPending || query.trim().length === 0}
              className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Search size={16} />
              {isPending ? "Searching…" : "Search"}
            </button>
          </form>

          {/* loading */}
          {isPending && (
            <p className="text-sm text-gray-500" role="status">
              检索中…
            </p>
          )}

          {/* error */}
          {isError && (
            <div
              role="alert"
              className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
            >
              {errorMessage(error)}
            </div>
          )}

          {/* empty */}
          {showEmpty && (
            <p className="text-sm text-gray-500">没有找到相关结果。</p>
          )}

          {/* results */}
          {contexts.length > 0 && (
            <ul className="space-y-3">
              {contexts.map((ctx) => (
                <li key={ctx.chunk_id}>
                  <ContextCard context={ctx} onOpenDocument={openDocument} />
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* sidebar: retrieval controls (always) + subgraph (after a search) */}
        <aside className="space-y-6 lg:order-2">
          <RetrievalControls value={controls} onChange={setControls} />

          {subgraph && (
            <SubgraphPanel subgraph={subgraph} height={420} />
          )}
        </aside>
      </div>
    </div>
  );
}

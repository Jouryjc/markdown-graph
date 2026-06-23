import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";

import { ApiError } from "../api/client";
import { useQuerySearch } from "../api/hooks";
import type { QueryMode, QueryRequest, QueryResponse } from "../api/types";
import ContextCard from "../components/ContextCard";
import RetrievalControls, {
  type RetrievalControlsValue,
} from "../components/RetrievalControls";
import SubgraphPanel from "../components/SubgraphPanel";

const DEFAULT_CONTROLS: RetrievalControlsValue = {
  k: 8,
  schemes: ["dual"],
  graph_weight: 0.5,
  per_doc_cap: 2,
  hops: 2,
};

// Every scheme that can be compared. Hooks must be called unconditionally, so
// we instantiate one mutation per scheme up front and only render the columns
// for the currently-selected schemes.
const ALL_SCHEMES: readonly QueryMode[] = ["dual", "vector", "file"];

const SCHEME_LABELS: Record<QueryMode, string> = {
  dual: "Dual",
  vector: "Vector",
  file: "File",
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "检索失败，请稍后重试。";
}

// Per-scheme search state: the mutation result plus the round-trip latency we
// measure with performance.now() so columns can be compared head-to-head.
interface SchemeSearch {
  scheme: QueryMode;
  data: QueryResponse | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  elapsedMs: number | null;
}

export default function SearchPage() {
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [controls, setControls] =
    useState<RetrievalControlsValue>(DEFAULT_CONTROLS);

  // One mutation per scheme. Order is fixed (ALL_SCHEMES) so the hook call
  // order never changes between renders.
  const dualSearch = useQuerySearch();
  const vectorSearch = useQuerySearch();
  const fileSearch = useQuerySearch();
  const searches: Record<QueryMode, ReturnType<typeof useQuerySearch>> = {
    dual: dualSearch,
    vector: vectorSearch,
    file: fileSearch,
  };

  // Round-trip latency per scheme, keyed by scheme. null until a search
  // completes for that scheme.
  const [elapsed, setElapsed] = useState<Partial<Record<QueryMode, number>>>(
    {},
  );

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length === 0) return;
    if (controls.schemes.length === 0) return;

    setElapsed({});

    for (const scheme of controls.schemes) {
      const body: QueryRequest = {
        query: trimmed,
        k: controls.k,
        mode: scheme,
        graph_weight: controls.graph_weight,
        per_doc_cap: controls.per_doc_cap,
        hops: controls.hops,
      };
      const startedAt = performance.now();
      searches[scheme].mutate(body, {
        onSettled: () => {
          const ms = performance.now() - startedAt;
          setElapsed((prev) => ({ ...prev, [scheme]: ms }));
        },
      });
    }
  };

  const openDocument = (docId: string) => {
    navigate(`/doc/${encodeURIComponent(docId)}`);
  };

  // Selected schemes, in canonical order, with their live state attached.
  const activeSchemes: SchemeSearch[] = ALL_SCHEMES.filter((s) =>
    controls.schemes.includes(s),
  ).map((scheme) => {
    const s = searches[scheme];
    return {
      scheme,
      data: s.data,
      isPending: s.isPending,
      isError: s.isError,
      error: s.error,
      isSuccess: s.isSuccess,
      elapsedMs: elapsed[scheme] ?? null,
    };
  });

  const single = activeSchemes.length === 1;

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
              disabled={
                query.trim().length === 0 || controls.schemes.length === 0
              }
              className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Search size={16} />
              Search
            </button>
          </form>

          {single ? (
            <SingleColumn
              search={activeSchemes[0]}
              onOpenDocument={openDocument}
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {activeSchemes.map((s) => (
                <SchemeColumn
                  key={s.scheme}
                  search={s}
                  onOpenDocument={openDocument}
                />
              ))}
            </div>
          )}
        </div>

        {/* sidebar: retrieval controls (always) + subgraph (single mode only) */}
        <aside className="space-y-6 lg:order-2">
          <RetrievalControls value={controls} onChange={setControls} />

          {single && activeSchemes[0].data?.subgraph && (
            <SubgraphPanel
              subgraph={activeSchemes[0].data.subgraph}
              height={420}
            />
          )}
        </aside>
      </div>
    </div>
  );
}

/**
 * Single-scheme layout (one scheme selected): keeps the original behaviour —
 * a flat result list in the main column, with the subgraph in the sidebar
 * (rendered by the parent). No column chrome.
 */
function SingleColumn({
  search,
  onOpenDocument,
}: {
  search: SchemeSearch;
  onOpenDocument: (docId: string) => void;
}) {
  const contexts = search.data?.contexts ?? [];
  const showEmpty = search.isSuccess && contexts.length === 0;

  return (
    <div className="space-y-4">
      {search.isPending && (
        <p className="text-sm text-gray-500" role="status">
          检索中…
        </p>
      )}

      {search.isError && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {errorMessage(search.error)}
        </div>
      )}

      {showEmpty && (
        <p className="text-sm text-gray-500">没有找到相关结果。</p>
      )}

      {contexts.length > 0 && (
        <ul className="space-y-3">
          {contexts.map((ctx) => (
            <li key={ctx.chunk_id}>
              <ContextCard context={ctx} onOpenDocument={onOpenDocument} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One column in the side-by-side compare view: scheme title + result count +
 * round-trip latency, then an independent loading / error / empty / results
 * body. The dual column additionally exposes a collapsible subgraph so it
 * doesn't crowd the comparison.
 */
function SchemeColumn({
  search,
  onOpenDocument,
}: {
  search: SchemeSearch;
  onOpenDocument: (docId: string) => void;
}) {
  const [showSubgraph, setShowSubgraph] = useState(false);

  const contexts = search.data?.contexts ?? [];
  const showEmpty = search.isSuccess && contexts.length === 0;
  const subgraph =
    search.scheme === "dual" ? search.data?.subgraph ?? null : null;

  let body: ReactNode;
  if (search.isPending) {
    body = (
      <p className="text-sm text-gray-500" role="status">
        检索中…
      </p>
    );
  } else if (search.isError) {
    body = (
      <div
        role="alert"
        className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
      >
        {errorMessage(search.error)}
      </div>
    );
  } else if (showEmpty) {
    body = <p className="text-sm text-gray-500">没有找到相关结果。</p>;
  } else if (contexts.length > 0) {
    body = (
      <ul className="space-y-3">
        {contexts.map((ctx) => (
          <li key={ctx.chunk_id}>
            <ContextCard context={ctx} onOpenDocument={onOpenDocument} />
          </li>
        ))}
      </ul>
    );
  } else {
    body = null;
  }

  return (
    <section
      aria-label={`${SCHEME_LABELS[search.scheme]} 结果`}
      className="min-w-0 space-y-3 rounded border border-gray-200 bg-gray-50 p-3"
    >
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-800">
          {SCHEME_LABELS[search.scheme]}
        </h2>
        <span className="text-xs text-gray-400">
          {search.isSuccess ? `${contexts.length} 结果` : "—"}
          {search.elapsedMs != null && (
            <> · {Math.round(search.elapsedMs)} ms</>
          )}
        </span>
      </header>

      {body}

      {subgraph && subgraph.nodes.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowSubgraph((v) => !v)}
            className="text-xs font-medium text-blue-600 hover:underline"
          >
            {showSubgraph ? "隐藏子图" : "查看子图"}
          </button>
          {showSubgraph && (
            <div className="mt-2">
              <SubgraphPanel subgraph={subgraph} height={320} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

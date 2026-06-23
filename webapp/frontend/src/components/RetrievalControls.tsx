import type { QueryMode } from "../api/types";

export interface RetrievalControlsValue {
  k: number;
  /**
   * Retrieval schemes to compare. At least one is always selected; the UI
   * blocks deselecting the last one. Each selected scheme becomes its own
   * column / query on the SearchPage.
   */
  schemes: QueryMode[];
  graph_weight: number;
  per_doc_cap: number | null;
  hops: number;
}

export interface RetrievalControlsProps {
  value: RetrievalControlsValue;
  onChange: (value: RetrievalControlsValue) => void;
}

const SCHEME_OPTIONS: readonly QueryMode[] = ["dual", "vector", "file"];

function clampInt(raw: string, min: number, fallback: number): number {
  const n = parseInt(raw, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(min, n);
}

/**
 * Controlled retrieval-parameter panel. No internal fetching or state — every
 * change is forwarded through `onChange` with the full next value, so this is
 * fully unit-testable.
 *
 * `schemes` is a multi-select (dual / vector / file). At least one must stay
 * selected, so unchecking the final scheme is blocked. graph_weight and hops
 * only matter for dual retrieval, so they are disabled unless dual is selected.
 * k and per_doc_cap are global.
 */
export default function RetrievalControls({
  value,
  onChange,
}: RetrievalControlsProps) {
  const hasDual = value.schemes.includes("dual");

  const patch = (partial: Partial<RetrievalControlsValue>) =>
    onChange({ ...value, ...partial });

  const toggleScheme = (scheme: QueryMode) => {
    const selected = value.schemes.includes(scheme);
    if (selected) {
      // Block deselecting the last scheme — at least one must remain.
      if (value.schemes.length <= 1) return;
      patch({ schemes: value.schemes.filter((s) => s !== scheme) });
      return;
    }
    // Keep a stable canonical order (dual, vector, file).
    patch({
      schemes: SCHEME_OPTIONS.filter(
        (s) => value.schemes.includes(s) || s === scheme,
      ),
    });
  };

  const unlimited = value.per_doc_cap == null;

  return (
    <div className="space-y-4 rounded border border-gray-200 bg-white p-4">
      {/* scheme multi-select */}
      <div>
        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
          Schemes
        </span>
        <div
          role="group"
          aria-label="Retrieval schemes"
          className="inline-flex overflow-hidden rounded border border-gray-300"
        >
          {SCHEME_OPTIONS.map((scheme) => {
            const selected = value.schemes.includes(scheme);
            const isLast = selected && value.schemes.length <= 1;
            return (
              <button
                key={scheme}
                type="button"
                role="checkbox"
                aria-checked={selected}
                disabled={isLast}
                onClick={() => toggleScheme(scheme)}
                className={[
                  "px-3 py-1.5 text-sm font-medium capitalize",
                  selected
                    ? "bg-blue-600 text-white"
                    : "bg-white text-gray-700 hover:bg-gray-50",
                  isLast ? "cursor-not-allowed" : "",
                ].join(" ")}
              >
                {scheme}
              </button>
            );
          })}
        </div>
      </div>

      {/* k */}
      <div>
        <label
          htmlFor="rc-k"
          className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500"
        >
          Results (k)
        </label>
        <input
          id="rc-k"
          type="number"
          min={1}
          value={value.k}
          onChange={(e) => patch({ k: clampInt(e.target.value, 1, value.k) })}
          className="w-24 rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </div>

      {/* graph_weight (dual only) */}
      <div>
        <label
          htmlFor="rc-graph-weight"
          className="mb-1 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-gray-500"
        >
          <span>Graph weight</span>
          <span className="font-mono text-gray-700">
            {value.graph_weight.toFixed(2)}
          </span>
        </label>
        <input
          id="rc-graph-weight"
          type="range"
          min={0}
          max={1}
          step={0.05}
          disabled={!hasDual}
          value={value.graph_weight}
          onChange={(e) => patch({ graph_weight: parseFloat(e.target.value) })}
          className="w-full disabled:opacity-40"
        />
      </div>

      {/* per_doc_cap (global) */}
      <div>
        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
          Per-document cap
        </span>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={unlimited}
              onChange={(e) =>
                patch({ per_doc_cap: e.target.checked ? null : 2 })
              }
            />
            Unlimited
          </label>
          <input
            type="number"
            min={1}
            aria-label="Per-document cap"
            disabled={unlimited}
            value={unlimited ? "" : value.per_doc_cap ?? 0}
            onChange={(e) =>
              patch({
                per_doc_cap: clampInt(e.target.value, 1, value.per_doc_cap ?? 1),
              })
            }
            className="w-24 rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400"
          />
        </div>
      </div>

      {/* hops (dual only) */}
      <div>
        <label
          htmlFor="rc-hops"
          className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500"
        >
          Hops
        </label>
        <input
          id="rc-hops"
          type="number"
          min={1}
          disabled={!hasDual}
          value={value.hops}
          onChange={(e) =>
            patch({ hops: clampInt(e.target.value, 1, value.hops) })
          }
          className="w-24 rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-400"
        />
      </div>
    </div>
  );
}

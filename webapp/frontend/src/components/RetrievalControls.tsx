import type { QueryMode } from "../api/types";

export interface RetrievalControlsValue {
  k: number;
  mode: QueryMode;
  graph_weight: number;
  per_doc_cap: number | null;
  hops: number;
}

export interface RetrievalControlsProps {
  value: RetrievalControlsValue;
  onChange: (value: RetrievalControlsValue) => void;
}

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
 * graph_weight and hops only matter for dual retrieval, so they are disabled
 * when `mode === "vector"`.
 */
export default function RetrievalControls({
  value,
  onChange,
}: RetrievalControlsProps) {
  const isVector = value.mode === "vector";

  const patch = (partial: Partial<RetrievalControlsValue>) =>
    onChange({ ...value, ...partial });

  const unlimited = value.per_doc_cap == null;

  return (
    <div className="space-y-4 rounded border border-gray-200 bg-white p-4">
      {/* mode toggle */}
      <div>
        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">
          Mode
        </span>
        <div
          role="radiogroup"
          aria-label="Retrieval mode"
          className="inline-flex overflow-hidden rounded border border-gray-300"
        >
          {(["dual", "vector"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={value.mode === m}
              onClick={() => patch({ mode: m })}
              className={[
                "px-3 py-1.5 text-sm font-medium capitalize",
                value.mode === m
                  ? "bg-blue-600 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50",
              ].join(" ")}
            >
              {m}
            </button>
          ))}
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

      {/* graph_weight */}
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
          disabled={isVector}
          value={value.graph_weight}
          onChange={(e) => patch({ graph_weight: parseFloat(e.target.value) })}
          className="w-full disabled:opacity-40"
        />
      </div>

      {/* per_doc_cap */}
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

      {/* hops */}
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
          disabled={isVector}
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

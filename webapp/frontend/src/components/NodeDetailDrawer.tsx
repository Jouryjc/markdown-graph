import { X } from "lucide-react";

import { useNodeDetail } from "../api/hooks";
import type { NeighborRef } from "../api/types";
import { colorForType, labelForEdge } from "../lib/graphColors";

export interface NodeDetailDrawerProps {
  /** Node to inspect. When null, the drawer is hidden. */
  nodeId: string | null;
  /**
   * Optional explicit open flag. Defaults to `nodeId != null`, so callers may
   * either pass a nullable `nodeId` alone or control visibility separately.
   */
  open?: boolean;
  onClose: () => void;
  /** Click a neighbor to navigate to it. */
  onSelectNode?: (nodeId: string) => void;
}

function metaName(meta: Record<string, unknown>, fallback: string): string {
  const name = meta["name"];
  return typeof name === "string" && name.length > 0 ? name : fallback;
}

function TypeChip({ type }: { type: string }) {
  return (
    <span
      className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium text-white"
      style={{ backgroundColor: colorForType(type) }}
    >
      {type}
    </span>
  );
}

function NeighborRow({
  neighbor,
  onSelectNode,
}: {
  neighbor: NeighborRef;
  onSelectNode?: (nodeId: string) => void;
}) {
  const name = metaName(neighbor.meta, neighbor.id);
  const arrow = neighbor.direction === "out" ? "→" : "←";
  const content = (
    <div className="flex items-center gap-2">
      <TypeChip type={neighbor.type} />
      <span className="min-w-0 flex-1 truncate text-sm" title={name}>
        {name}
      </span>
      <span className="shrink-0 text-xs text-gray-500">
        {arrow} {labelForEdge(neighbor.edge_type)}
      </span>
    </div>
  );

  if (onSelectNode) {
    return (
      <button
        type="button"
        onClick={() => onSelectNode(neighbor.id)}
        className="w-full rounded px-2 py-1.5 text-left hover:bg-gray-50"
      >
        {content}
      </button>
    );
  }
  return <div className="px-2 py-1.5">{content}</div>;
}

/**
 * Slide-over panel showing a node's id/type/meta plus its 1-hop neighbors.
 * Fetches via the `useNodeDetail` react-query hook (no fetch happens while
 * `nodeId` is null thanks to the hook's `enabled` guard).
 */
export default function NodeDetailDrawer({
  nodeId,
  open,
  onClose,
  onSelectNode,
}: NodeDetailDrawerProps) {
  const isOpen = open ?? nodeId != null;
  const { data, isLoading, isError, error } = useNodeDetail(nodeId);

  if (!isOpen || nodeId == null) return null;

  const metaEntries = data ? Object.entries(data.node.meta) : [];

  return (
    <aside className="fixed right-0 top-0 z-40 flex h-full w-96 max-w-full flex-col border-l border-gray-200 bg-white shadow-xl">
      <header className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <h2 className="truncate text-sm font-semibold" title={nodeId}>
          {data ? metaName(data.node.meta, data.node.id) : nodeId}
        </h2>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="rounded p-1 text-gray-500 hover:bg-gray-100"
        >
          <X size={18} />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
        {isError && (
          <p className="text-sm text-red-600">
            {error instanceof Error ? error.message : "Failed to load node."}
          </p>
        )}

        {data && (
          <div className="space-y-4">
            <section className="space-y-1">
              <div className="flex items-center gap-2">
                <TypeChip type={data.node.type} />
                <code className="break-all text-xs text-gray-500">
                  {data.node.id}
                </code>
              </div>
            </section>

            {metaEntries.length > 0 && (
              <section>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  Meta
                </h3>
                <dl className="space-y-1">
                  {metaEntries.map(([key, val]) => (
                    <div key={key} className="flex gap-2 text-xs">
                      <dt className="shrink-0 font-medium text-gray-600">
                        {key}
                      </dt>
                      <dd className="min-w-0 break-words text-gray-800">
                        {typeof val === "string" ? val : JSON.stringify(val)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
                Neighbors ({data.neighbors.length})
              </h3>
              {data.neighbors.length === 0 ? (
                <p className="text-sm text-gray-400">No neighbors.</p>
              ) : (
                <ul className="-mx-2 divide-y divide-gray-100">
                  {data.neighbors.map((n) => (
                    <li key={`${n.direction}:${n.edge_type}:${n.id}`}>
                      <NeighborRow neighbor={n} onSelectNode={onSelectNode} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </aside>
  );
}

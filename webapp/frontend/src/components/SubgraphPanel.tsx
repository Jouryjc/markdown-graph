import { useState } from "react";

import type { Subgraph } from "../api/types";
import GraphCanvas from "./GraphCanvas";
import NodeDetailDrawer from "./NodeDetailDrawer";

export interface SubgraphPanelProps {
  /** The retrieval subgraph returned from /api/query. */
  subgraph: Subgraph;
  /** Canvas height in px. Defaults to 480. */
  height?: number;
}

/**
 * Self-contained right-hand panel for the SearchPage. Renders the query's
 * retrieval subgraph in a GraphCanvas and opens a NodeDetailDrawer when a node
 * is clicked. Owns only the locally-selected node id; node detail fetching is
 * delegated to NodeDetailDrawer (which self-disables when the id is null).
 *
 * GraphCanvas relies on a real canvas, so this panel is not rendered in jsdom
 * unit tests — callers/tests should mock GraphCanvas.
 */
export default function SubgraphPanel({
  subgraph,
  height = 480,
}: SubgraphPanelProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const nodeCount = subgraph.nodes.length;
  const edgeCount = subgraph.edges.length;

  return (
    <section className="space-y-2" aria-label="Retrieval subgraph">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-gray-700">检索子图</h2>
        <span className="text-xs text-gray-400">
          {nodeCount} 节点 · {edgeCount} 边
        </span>
      </header>

      <GraphCanvas
        nodes={subgraph.nodes}
        edges={subgraph.edges}
        height={height}
        selectedNodeId={selectedNodeId}
        onNodeClick={setSelectedNodeId}
      />

      <NodeDetailDrawer
        nodeId={selectedNodeId}
        open={selectedNodeId != null}
        onClose={() => setSelectedNodeId(null)}
        onSelectNode={setSelectedNodeId}
      />
    </section>
  );
}

import { useMemo } from "react";
import ForceGraph2D from "react-force-graph-2d";

import type { GraphEdge, GraphNode } from "../api/types";
import { colorForType } from "../lib/graphColors";

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick?: (nodeId: string) => void;
  /** Optional highlighted node (drawn with a ring). */
  selectedNodeId?: string | null;
  /** Canvas height in px. Defaults to 480. */
  height?: number;
}

/** Shape react-force-graph-2d expects for each node, plus our metadata. */
interface FGNode {
  id: string;
  type: string;
  label: string;
  color: string;
  [key: string]: unknown;
}

interface FGLink {
  source: string;
  target: string;
  type: string;
}

interface FGData {
  nodes: FGNode[];
  links: FGLink[];
}

function nodeLabel(node: GraphNode): string {
  const name = node.meta?.["name"];
  return typeof name === "string" && name.length > 0 ? name : node.id;
}

/**
 * Shared force-directed graph (canvas). Wraps react-force-graph-2d.
 *
 * Inputs use the backend graph shape ({id,type,meta} nodes, {src,dst,type}
 * edges); we transform them into the lib shape ({nodes, links:{source,target}})
 * inside a `useMemo` keyed on the inputs so the simulation does not re-layout
 * on unrelated re-renders.
 *
 * react-force-graph-2d relies on a real canvas/WebGL context that jsdom does
 * not provide, so this component is only exercised in the browser. Unit tests
 * should not render it directly. We still guard against empty data so the
 * component renders a friendly placeholder instead of an empty canvas.
 */
export default function GraphCanvas({
  nodes,
  edges,
  onNodeClick,
  selectedNodeId = null,
  height = 480,
}: GraphCanvasProps) {
  const data = useMemo<FGData>(() => {
    const nodeIds = new Set(nodes.map((n) => n.id));
    return {
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        label: nodeLabel(n),
        color: colorForType(n.type),
        meta: n.meta,
      })),
      // Drop dangling edges so the force layout never references a missing id.
      links: edges
        .filter((e) => nodeIds.has(e.src) && nodeIds.has(e.dst))
        .map((e) => ({ source: e.src, target: e.dst, type: e.type })),
    };
  }, [nodes, edges]);

  if (data.nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded border border-dashed border-gray-300 bg-white text-sm text-gray-400"
        style={{ height }}
      >
        No graph data
      </div>
    );
  }

  return (
    <div
      className="overflow-hidden rounded border border-gray-200 bg-white"
      style={{ height }}
    >
      <ForceGraph2D
        graphData={data}
        height={height}
        nodeRelSize={5}
        nodeColor={(node) => (node as FGNode).color}
        nodeLabel={(node) => {
          const n = node as FGNode;
          return `${n.label} (${n.type})`;
        }}
        linkColor={() => "#d1d5db"}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={1}
        onNodeClick={(node) => {
          const id = (node as FGNode).id;
          if (onNodeClick) onNodeClick(id);
        }}
        nodeCanvasObjectMode={(node) =>
          (node as FGNode).id === selectedNodeId ? "before" : undefined
        }
        nodeCanvasObject={(node, ctx) => {
          const n = node as FGNode & { x?: number; y?: number };
          if (n.id !== selectedNodeId || n.x == null || n.y == null) return;
          ctx.beginPath();
          ctx.arc(n.x, n.y, 8, 0, 2 * Math.PI, false);
          ctx.strokeStyle = "#111827";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }}
      />
    </div>
  );
}

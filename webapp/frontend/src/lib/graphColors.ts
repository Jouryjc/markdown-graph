// Node colors by type + human edge labels. Shared by GraphCanvas / drawers.

export const NODE_COLORS: Record<string, string> = {
  document: "#2563eb",
  section: "#7c3aed",
  chunk: "#0891b2",
  entity: "#dc2626",
  tag: "#ca8a04",
  // SAG bipartite hyperedge graph: event nodes (emerald) vs entity nodes (pink).
  event: "#059669",
  sag_entity: "#db2777",
};

const FALLBACK_COLOR = "#6b7280";

export function colorForType(type: string): string {
  return NODE_COLORS[type] ?? FALLBACK_COLOR;
}

const EDGE_LABELS: Record<string, string> = {
  contains: "contains",
  links_to: "links to",
  tagged: "tagged",
  mentions: "mentions",
  relates_to: "relates to",
  has_entity: "has entity",
};

export function labelForEdge(type: string): string {
  return EDGE_LABELS[type] ?? type;
}

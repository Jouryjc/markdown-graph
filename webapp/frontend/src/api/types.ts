// API types mirroring webapp/backend/schemas.py EXACTLY (field names + types).
// Keep in sync with the backend; it is the single source of truth.

// --- shared graph primitives ---
export interface GraphNode {
  id: string;
  type: string;
  meta: Record<string, unknown>;
}

export interface GraphEdge {
  src: string;
  dst: string;
  type: string;
}

export interface Subgraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// --- /api/stats ---
export interface Stats {
  documents: number;
  sections: number;
  chunks: number;
  entities: number;
  tags: number;
  nodes: number;
  edges: number;
  vectors: number;
}

// --- /api/query ---
// "file" is the LLM file-retrieval scheme: it ignores graph_weight/hops and
// returns an empty subgraph. The compare UI organizes multiple schemes
// client-side; the backend single-query contract is unchanged.
export type QueryMode = "dual" | "vector" | "file";

export interface QueryRequest {
  query: string;
  k: number;
  mode: QueryMode;
  graph_weight: number;
  per_doc_cap: number | null;
  hops: number;
}

export interface Context {
  chunk_id: string;
  text: string;
  score: number;
  doc_id: string;
  source_path: string;
  heading_path: string;
  from_graph: boolean;
}

export interface QueryResponse {
  contexts: Context[];
  subgraph: Subgraph;
}

// --- /api/graph and /api/graph/expand ---
export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total_nodes: number;
}

// --- /api/node/{node_id} ---
export interface NeighborRef {
  id: string;
  type: string;
  meta: Record<string, unknown>;
  edge_type: string;
  direction: "out" | "in";
}

export interface NodeDetail {
  node: GraphNode;
  neighbors: NeighborRef[];
}

// --- /api/documents and /api/document/{doc_id} ---
export interface DocumentSummary {
  id: string;
  path: string;
  chunk_count: number;
}

export interface DocumentChunk {
  id: string;
  section_path: string;
  text: string;
}

export interface DocumentMeta {
  id: string;
  path: string;
  frontmatter: Record<string, unknown>;
}

export interface DocumentDetail {
  document: DocumentMeta;
  chunks: DocumentChunk[];
  links: string[];
}

// --- /api/entities ---
export interface EntitySummary {
  id: string;
  name: string;
  type: string;
  mentions: number;
}

// --- /api/index ---
export interface IndexRequest {
  paths: string[];
  full: boolean;
}

export interface IndexReport {
  indexed: number;
  unchanged: number;
  removed: number;
  reclaimed: number;
  entities: number;
  errors: string[][];
}

// --- /api/upload and /api/jobs/{job_id} ---
export type JobState =
  | "pending"
  | "extracting"
  | "indexing"
  | "embedding"
  | "extracting_entities"
  | "done"
  | "error";

export interface UploadAccepted {
  job_id: string;
}

export interface JobStatus {
  job_id: string;
  state: JobState;
  phase: string;
  processed: number;
  total: number;
  markdown_files: number;
  report: IndexReport | null;
  error: string | null;
}

// --- /api/health ---
export interface Health {
  status: string;
}

// --- /api/config ---
// Mirrors webapp/backend/config_schema.py / config_store.py. The schema there
// is the single source of truth; keep these in sync.
export type ConfigFieldType = "string" | "int" | "url" | "secret";
export type ConfigSource = "overlay" | "env" | "default";

export interface ConfigField {
  key: string;
  label: string;
  type: ConfigFieldType;
  value: string;
  default: string;
  source: ConfigSource;
  secret: boolean;
  high_risk: boolean;
  applies: "live" | "rebuild";
  description: string;
  is_set: boolean;
}

export interface ConfigGroup {
  key: string;
  label: string;
  fields: ConfigField[];
}

export interface ConfigResponse {
  groups: ConfigGroup[];
}

export interface UpdateConfigRequest {
  values: Record<string, string | null>;
}

export interface UpdateConfigResponse {
  config: ConfigResponse;
  warnings: string[];
}

export interface ResetConfigResponse {
  config: ConfigResponse;
}

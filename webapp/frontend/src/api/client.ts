// Typed fetch client. One async function per backend endpoint. Throws on
// non-2xx with the parsed `detail` from the JSON body when available.

import type {
  DocumentDetail,
  DocumentSummary,
  EntitySummary,
  GraphResponse,
  IndexReport,
  IndexRequest,
  NodeDetail,
  QueryRequest,
  QueryResponse,
  Stats,
  Subgraph,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // body not JSON; keep status-text detail
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export function getHealth(): Promise<{ status: string }> {
  return request<{ status: string }>("/health");
}

export function getStats(): Promise<Stats> {
  return request<Stats>("/stats");
}

export function postQuery(body: QueryRequest): Promise<QueryResponse> {
  return request<QueryResponse>("/query", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getGraph(limit?: number): Promise<GraphResponse> {
  const qs = limit != null ? `?limit=${limit}` : "";
  return request<GraphResponse>(`/graph${qs}`);
}

export function expandGraph(seeds: string[], hops = 2): Promise<Subgraph> {
  const qs = `?seeds=${encodeURIComponent(seeds.join(","))}&hops=${hops}`;
  return request<Subgraph>(`/graph/expand${qs}`);
}

export function getNode(nodeId: string): Promise<NodeDetail> {
  return request<NodeDetail>(`/node/${encodeURIComponent(nodeId)}`);
}

export function getDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>("/documents");
}

export function getDocument(docId: string): Promise<DocumentDetail> {
  return request<DocumentDetail>(`/document/${encodeURIComponent(docId)}`);
}

export function getEntities(limit = 20): Promise<EntitySummary[]> {
  return request<EntitySummary[]>(`/entities?limit=${limit}`);
}

export function postIndex(body: IndexRequest): Promise<IndexReport> {
  return request<IndexReport>("/index", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

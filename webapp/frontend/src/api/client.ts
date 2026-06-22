// Typed fetch client. One async function per backend endpoint. Throws on
// non-2xx with the parsed `detail` from the JSON body when available.

import type {
  ConfigResponse,
  DocumentDetail,
  DocumentSummary,
  EntitySummary,
  GraphResponse,
  IndexReport,
  IndexRequest,
  JobStatus,
  NodeDetail,
  QueryRequest,
  QueryResponse,
  ResetConfigResponse,
  Stats,
  Subgraph,
  UpdateConfigResponse,
  UploadAccepted,
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

// --- /api/upload (multipart) ---
// Uses XMLHttpRequest to surface upload progress (0..1). Rejects with ApiError
// on non-2xx, parsing the JSON `detail` field when present.
export function uploadArchive(
  file: File,
  full: boolean,
  onProgress?: (fraction: number) => void,
): Promise<UploadAccepted> {
  return new Promise<UploadAccepted>((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("full", full ? "true" : "false");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/upload`);

    if (onProgress) {
      xhr.upload.onprogress = (ev: ProgressEvent) => {
        if (ev.lengthComputable && ev.total > 0) {
          onProgress(ev.loaded / ev.total);
        }
      };
    }

    xhr.onload = () => {
      const status = xhr.status;
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = null;
      }
      if (status >= 200 && status < 300) {
        resolve(body as UploadAccepted);
        return;
      }
      let detail = `${status} ${xhr.statusText}`;
      if (
        body &&
        typeof (body as { detail?: unknown }).detail === "string"
      ) {
        detail = (body as { detail: string }).detail;
      }
      reject(new ApiError(status, detail));
    };

    xhr.onerror = () => reject(new ApiError(0, "network error during upload"));
    xhr.onabort = () => reject(new ApiError(0, "upload aborted"));

    xhr.send(form);
  });
}

// --- /api/jobs/{job_id} ---
export function getJob(jobId: string): Promise<JobStatus> {
  return request<JobStatus>(`/jobs/${encodeURIComponent(jobId)}`);
}

// --- /api/config ---
export function getConfig(): Promise<ConfigResponse> {
  return request<ConfigResponse>("/config");
}

// Only the dirty fields go in `values`; null removes a key from the overlay
// (falling back to env/default).
export function updateConfig(
  values: Record<string, string | null>,
): Promise<UpdateConfigResponse> {
  return request<UpdateConfigResponse>("/config", {
    method: "PUT",
    body: JSON.stringify({ values }),
  });
}

export function resetConfig(): Promise<ResetConfigResponse> {
  return request<ResetConfigResponse>("/config/reset", { method: "POST" });
}

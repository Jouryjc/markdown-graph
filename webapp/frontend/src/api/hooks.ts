// react-query hooks wrapping the typed client functions.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getConfig,
  getDocument,
  getDocuments,
  getEntities,
  getGraph,
  getJob,
  getNode,
  getSagStatus,
  getStats,
  postQuery,
  postSagBuild,
  postSagSearch,
  resetConfig,
  updateConfig,
  uploadArchive,
} from "./client";
import type {
  ConfigResponse,
  DocumentDetail,
  DocumentSummary,
  EntitySummary,
  GraphResponse,
  JobStatus,
  NodeDetail,
  QueryRequest,
  QueryResponse,
  ResetConfigResponse,
  SAGSearchRequest,
  SAGSearchResponse,
  SAGStatus,
  Stats,
  UpdateConfigResponse,
  UploadAccepted,
} from "./types";

export function useStats(): UseQueryResult<Stats> {
  return useQuery({ queryKey: ["stats"], queryFn: getStats });
}

export function useQuerySearch(): UseMutationResult<
  QueryResponse,
  unknown,
  QueryRequest
> {
  return useMutation({ mutationFn: (body: QueryRequest) => postQuery(body) });
}

export function useGraph(limit?: number): UseQueryResult<GraphResponse> {
  return useQuery({
    queryKey: ["graph", limit ?? null],
    queryFn: () => getGraph(limit),
  });
}

export function useNodeDetail(
  nodeId: string | null,
): UseQueryResult<NodeDetail> {
  return useQuery({
    queryKey: ["node", nodeId],
    queryFn: () => getNode(nodeId as string),
    enabled: nodeId != null,
  });
}

export function useDocuments(): UseQueryResult<DocumentSummary[]> {
  return useQuery({ queryKey: ["documents"], queryFn: getDocuments });
}

export function useDocument(
  docId: string | null,
): UseQueryResult<DocumentDetail> {
  return useQuery({
    queryKey: ["document", docId],
    queryFn: () => getDocument(docId as string),
    enabled: docId != null,
  });
}

export function useEntities(limit = 20): UseQueryResult<EntitySummary[]> {
  return useQuery({
    queryKey: ["entities", limit],
    queryFn: () => getEntities(limit),
  });
}

// --- upload flow ---
export interface UploadArchiveVars {
  file: File;
  full: boolean;
  onProgress?: (fraction: number) => void;
}

export function useUploadArchive(): UseMutationResult<
  UploadAccepted,
  unknown,
  UploadArchiveVars
> {
  return useMutation({
    mutationFn: ({ file, full, onProgress }: UploadArchiveVars) =>
      uploadArchive(file, full, onProgress),
  });
}

// --- config flow ---
export function useConfig(): UseQueryResult<ConfigResponse> {
  return useQuery({ queryKey: ["config"], queryFn: getConfig });
}

export function useUpdateConfig(): UseMutationResult<
  UpdateConfigResponse,
  unknown,
  Record<string, string | null>
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, string | null>) =>
      updateConfig(values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

export function useResetConfig(): UseMutationResult<
  ResetConfigResponse,
  unknown,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => resetConfig(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

// --- SAG flow ---
// build 端只返回 {job_id}；进度走 useJob(JobStatus)；最终计数走 useSagStatus。
// onSuccess 不立即 invalidate ["sag-status"]——计数只在 job 轮询到 done 后才准确，
// 由调用方在 job 完成时 invalidate。
export function useSagStatus(): UseQueryResult<SAGStatus> {
  return useQuery({ queryKey: ["sag-status"], queryFn: getSagStatus });
}

export function useSagBuild(): UseMutationResult<
  UploadAccepted,
  unknown,
  boolean
> {
  return useMutation({ mutationFn: (full: boolean) => postSagBuild(full) });
}

export function useSagSearch(): UseMutationResult<
  SAGSearchResponse,
  unknown,
  SAGSearchRequest
> {
  return useMutation({
    mutationFn: (body: SAGSearchRequest) => postSagSearch(body),
  });
}

// Thin invalidation helper: lets a component refresh a query (e.g. ["sag-status"]
// after a build job reaches a terminal state) without holding the query client
// directly.
export function useQueryClientInvalidate(): (queryKey: unknown[]) => void {
  const queryClient = useQueryClient();
  return (queryKey: unknown[]) => {
    queryClient.invalidateQueries({ queryKey });
  };
}

const JOB_TERMINAL = new Set<JobStatus["state"]>(["done", "error"]);

export function useJob(jobId: string | null): UseQueryResult<JobStatus> {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: jobId != null,
    // Poll while the job is still running; stop once terminal.
    refetchInterval: (query) => {
      const data = query.state.data as JobStatus | undefined;
      if (data && JOB_TERMINAL.has(data.state)) {
        return false;
      }
      return 1000;
    },
  });
}

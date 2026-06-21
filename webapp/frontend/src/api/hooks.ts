// react-query hooks wrapping the typed client functions.

import {
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  getDocument,
  getDocuments,
  getEntities,
  getGraph,
  getNode,
  getStats,
  postQuery,
} from "./client";
import type {
  DocumentDetail,
  DocumentSummary,
  EntitySummary,
  GraphResponse,
  NodeDetail,
  QueryRequest,
  QueryResponse,
  Stats,
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

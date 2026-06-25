import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  Boxes,
  Hammer,
  Loader2,
  Search,
  Tag,
} from "lucide-react";

import { ApiError } from "../api/client";
import {
  useJob,
  useQueryClientInvalidate,
  useSagBuild,
  useSagSearch,
  useSagStatus,
} from "../api/hooks";
import type {
  JobState,
  SAGEntityRef,
  SAGEventHit,
  SAGSearchRequest,
} from "../api/types";
import { colorForType } from "../lib/graphColors";
import GraphCanvas from "../components/GraphCanvas";

// SAG build phases. The backend drives a SAG job through pending → sag_indexing
// → done; the other phases never fire for a SAG build but JobState is shared.
const STATE_LABEL: Record<JobState, string> = {
  pending: "排队中…",
  extracting: "正在解压归档…",
  indexing: "正在索引文档…",
  embedding: "正在生成向量…",
  extracting_entities: "正在抽取实体与关系…",
  sag_indexing: "正在构建 SAG 索引…",
  done: "构建完成",
  error: "构建失败",
};

const TERMINAL_STATES: ReadonlySet<JobState> = new Set<JobState>([
  "done",
  "error",
]);

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "请求失败，请稍后重试。";
}

export default function SAGPage() {
  return (
    <div className="space-y-6 p-6">
      <h1 className="flex items-center gap-2 text-xl font-semibold">
        <Boxes size={20} className="text-emerald-600" />
        SAG 事件/实体检索
      </h1>
      <SAGStatusBar />
      <SAGSearchSection />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status / build bar — drives the SAG index build job and shows counts.
// ---------------------------------------------------------------------------
function SAGStatusBar() {
  const status = useSagStatus();
  const build = useSagBuild();
  const invalidate = useQueryClientInvalidate();

  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);

  // When the build job reaches a terminal state, refresh the status counts and
  // stop polling by clearing the job id.
  useEffect(() => {
    const state = job.data?.state;
    if (jobId != null && state != null && TERMINAL_STATES.has(state)) {
      invalidate(["sag-status"]);
      setJobId(null);
    }
  }, [job.data?.state, jobId, invalidate]);

  const startBuild = (full: boolean) => {
    build.mutate(full, {
      onSuccess: (accepted) => setJobId(accepted.job_id),
    });
  };

  const building = jobId != null && job.data?.state !== "error";
  const data = status.data;

  return (
    <section
      aria-label="SAG 索引状态"
      className="rounded border border-gray-200 bg-gray-50 p-4"
    >
      {status.isLoading && (
        <p className="text-sm text-gray-500" role="status">
          加载状态…
        </p>
      )}

      {data && !data.built && !building && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-gray-600">
            尚未构建 SAG 索引。点击右侧按钮基于现有文档抽取事件/实体层。
          </p>
          <button
            type="button"
            onClick={() => startBuild(false)}
            disabled={build.isPending}
            className="inline-flex items-center gap-1.5 rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Hammer size={16} />
            构建 SAG 索引
          </button>
        </div>
      )}

      {data && data.built && !building && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-4 text-sm text-gray-700">
            <span>
              事件 <strong className="tabular-nums">{data.events}</strong>
            </span>
            <span>
              实体 <strong className="tabular-nums">{data.entities}</strong>
            </span>
            <span>
              联结 <strong className="tabular-nums">{data.links}</strong>
            </span>
            <span className="text-xs text-gray-400">
              {data.has_embedder ? "已配置 embedder（向量召回）" : "无 embedder（实体匹配 + 重叠排序）"}
            </span>
          </div>
          <button
            type="button"
            onClick={() => startBuild(true)}
            disabled={build.isPending}
            className="inline-flex items-center gap-1.5 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Hammer size={16} />
            重建
          </button>
        </div>
      )}

      {building && (
        <div className="space-y-2" role="status">
          <div className="flex items-center gap-2 text-sm text-gray-700">
            <Loader2 size={16} className="animate-spin text-emerald-600" />
            {job.data ? STATE_LABEL[job.data.state] : "排队中…"}
            {job.data && job.data.total > 0 && (
              <span className="text-xs text-gray-400 tabular-nums">
                {job.data.processed}/{job.data.total}
              </span>
            )}
          </div>
          {job.data && job.data.total > 0 && (
            <div className="h-1.5 w-full overflow-hidden rounded bg-gray-200">
              <div
                className="h-full bg-emerald-500 transition-all"
                style={{
                  width: `${Math.min(
                    100,
                    Math.round((job.data.processed / job.data.total) * 100),
                  )}%`,
                }}
              />
            </div>
          )}
        </div>
      )}

      {build.isError && (
        <div
          role="alert"
          className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {build.error instanceof ApiError && build.error.status === 409
            ? "已有构建任务正在进行，请等待其完成后再试。"
            : errorMessage(build.error)}
        </div>
      )}

      {jobId != null && job.data?.state === "error" && (
        <div
          role="alert"
          className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {job.data.error ?? "构建失败。"}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Search section — query controls + results (events list vs entities panel).
// ---------------------------------------------------------------------------
function SAGSearchSection() {
  const search = useSagSearch();

  const [query, setQuery] = useState("");
  const [k, setK] = useState(8);
  const [maxHops, setMaxHops] = useState(2);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length === 0) return;
    const body: SAGSearchRequest = { query: trimmed, k, max_hops: maxHops };
    search.mutate(body);
  };

  const data = search.data;
  const events = data?.events ?? [];
  const entities = data?.entities ?? [];
  const trace = data?.trace;
  const graph = data?.graph;
  const showEmpty = search.isSuccess && events.length === 0;

  // entity_id -> number of events it connects (from graph edges), for the panel.
  const entityEventCounts = countEntityEvents(graph?.edges ?? []);

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          aria-label="SAG Query"
          placeholder="搜索事件，例如「项目里程碑」…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="min-w-0 flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        />
        <label className="flex items-center gap-1 text-xs text-gray-500">
          k
          <input
            type="number"
            aria-label="k"
            min={1}
            value={k}
            onChange={(e) => setK(Math.max(1, Number(e.target.value) || 1))}
            className="w-16 rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="flex items-center gap-1 text-xs text-gray-500">
          max_hops
          <input
            type="number"
            aria-label="max_hops"
            min={0}
            max={4}
            value={maxHops}
            onChange={(e) =>
              setMaxHops(Math.min(4, Math.max(0, Number(e.target.value) || 0)))
            }
            className="w-16 rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={query.trim().length === 0 || search.isPending}
          className="inline-flex items-center gap-1.5 rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Search size={16} />
          Search
        </button>
      </form>

      {search.isPending && (
        <p className="text-sm text-gray-500" role="status">
          检索中…
        </p>
      )}

      {search.isError && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {search.error instanceof ApiError && search.error.status === 409
            ? "尚未构建 SAG 索引，请先在上方点击「构建 SAG 索引」。"
            : errorMessage(search.error)}
        </div>
      )}

      {showEmpty && (
        <p className="text-sm text-gray-500">没有找到相关事件。</p>
      )}

      {events.length > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
          {/* main: events list */}
          <section
            aria-label="Events"
            className="min-w-0 space-y-3 lg:order-1"
          >
            <h2 className="text-sm font-semibold text-gray-800">
              事件 ({events.length})
            </h2>
            <ul className="space-y-3">
              {events.map((ev) => (
                <li key={ev.event_id}>
                  <SAGEventCard event={ev} />
                </li>
              ))}
            </ul>
          </section>

          {/* sidebar: entities panel (visually distinct chip grid) */}
          <aside className="space-y-6 lg:order-2">
            <SAGEntityPanel
              entities={entities}
              eventCounts={entityEventCounts}
            />
            {graph && graph.nodes.length > 0 && (
              <section aria-label="SAG 超边图" className="space-y-2">
                <h2 className="text-sm font-semibold text-gray-700">
                  事件↔实体超边图
                </h2>
                <GraphCanvas
                  nodes={graph.nodes}
                  edges={graph.edges}
                  height={360}
                />
                {trace && (
                  <p className="text-xs text-gray-500">
                    查询实体 {trace.query_entities.length} · 种子{" "}
                    {trace.seed_event_ids.length} · 扩展{" "}
                    {trace.expanded_event_ids.length} · 排序{" "}
                    {trace.ranked_event_ids.length}
                  </p>
                )}
              </section>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function countEntityEvents(
  edges: { src: string; dst: string; type: string }[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const e of edges) {
    if (e.type !== "has_entity") continue;
    // edge src=event, dst=entity (bipartite has_entity).
    counts[e.dst] = (counts[e.dst] ?? 0) + 1;
  }
  return counts;
}

// ---------------------------------------------------------------------------
// SAGEventCard — one event: title + category/score/hop badges + summary +
// keywords + expandable content/source + this event's entity chips.
// ---------------------------------------------------------------------------
function SAGEventCard({ event }: { event: SAGEventHit }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <article className="space-y-2 rounded border border-gray-200 bg-white p-3 shadow-sm">
      <header className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">
          {event.title || "(无标题事件)"}
        </h3>
        <div className="flex shrink-0 items-center gap-1">
          {event.category && (
            <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs font-medium text-emerald-700">
              {event.category}
            </span>
          )}
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500 tabular-nums">
            {event.score.toFixed(2)}
          </span>
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
            hop {event.hop}
          </span>
        </div>
      </header>

      {event.summary && (
        <p className="text-sm text-gray-700">{event.summary}</p>
      )}

      {event.keywords.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {event.keywords.map((kw) => (
            <span
              key={kw}
              className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
            >
              {kw}
            </span>
          ))}
        </div>
      )}

      {event.entities.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {event.entities.map((ent) => (
            <EntityChip key={ent.id} entity={ent} />
          ))}
        </div>
      )}

      {(event.content || event.source_path) && (
        <div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-emerald-600 hover:underline"
          >
            {expanded ? "收起" : "展开内容/来源"}
          </button>
          {expanded && (
            <div className="mt-2 space-y-1">
              {event.content && (
                <p className="whitespace-pre-wrap text-sm text-gray-600">
                  {event.content}
                </p>
              )}
              {event.source_path && (
                <p className="text-xs text-gray-400">
                  {event.source_path}
                  {event.heading_path ? ` · ${event.heading_path}` : ""}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function EntityChip({ entity }: { entity: SAGEntityRef }) {
  const color = colorForType("sag_entity");
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
      style={{ borderColor: color, color }}
      title={entity.type}
    >
      <Tag size={10} />
      {entity.name}
    </span>
  );
}

// ---------------------------------------------------------------------------
// SAGEntityPanel — entities grouped by type, distinct from the event cards.
// ---------------------------------------------------------------------------
function SAGEntityPanel({
  entities,
  eventCounts,
}: {
  entities: SAGEntityRef[];
  eventCounts: Record<string, number>;
}) {
  // Group by type, preserving first-seen order of types.
  const groups: { type: string; items: SAGEntityRef[] }[] = [];
  const index: Record<string, number> = {};
  for (const ent of entities) {
    const type = ent.type || "tags";
    if (index[type] == null) {
      index[type] = groups.length;
      groups.push({ type, items: [] });
    }
    groups[index[type]].items.push(ent);
  }

  return (
    <section
      aria-label="Entities"
      className="space-y-3 rounded border border-pink-200 bg-pink-50/40 p-3"
    >
      <h2 className="text-sm font-semibold text-gray-800">
        实体 ({entities.length})
      </h2>
      {groups.length === 0 ? (
        <p className="text-xs text-gray-400">无实体</p>
      ) : (
        groups.map((group) => (
          <div key={group.type} className="space-y-1">
            <h3 className="text-xs font-medium uppercase tracking-wide text-gray-500">
              {group.type}
            </h3>
            <div className="flex flex-wrap gap-1">
              {group.items.map((ent) => (
                <EntityChipWithCount
                  key={ent.id}
                  entity={ent}
                  count={eventCounts[ent.id] ?? 0}
                />
              ))}
            </div>
          </div>
        ))
      )}
    </section>
  );
}

function EntityChipWithCount({
  entity,
  count,
}: {
  entity: SAGEntityRef;
  count: number;
}): ReactNode {
  const color = colorForType("sag_entity");
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border bg-white px-2 py-0.5 text-xs"
      style={{ borderColor: color, color }}
    >
      {entity.name}
      {count > 0 && (
        <span className="text-[10px] text-gray-400 tabular-nums">{count}</span>
      )}
    </span>
  );
}

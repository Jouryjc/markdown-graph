import {
  AlertCircle,
  BarChart3,
  Boxes,
  FileText,
  Hash,
  Layers,
  Loader2,
  Network,
  Tag,
  Type,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";

import type { LucideProps } from "lucide-react";

import { useEntities, useStats } from "../api/hooks";
import type { EntitySummary, Stats } from "../api/types";
import { colorForType } from "../lib/graphColors";

const ENTITY_COLOR = colorForType("entity");

interface StatCardDef {
  key: keyof Stats;
  label: string;
  Icon: ComponentType<LucideProps>;
}

// Ordered to match the dashboard layout: content counts first, then graph totals.
const STAT_CARDS: StatCardDef[] = [
  { key: "documents", label: "Documents", Icon: FileText },
  { key: "sections", label: "Sections", Icon: Layers },
  { key: "chunks", label: "Chunks", Icon: Type },
  { key: "entities", label: "Entities", Icon: Users },
  { key: "tags", label: "Tags", Icon: Tag },
  { key: "nodes", label: "Nodes", Icon: Network },
  { key: "edges", label: "Edges", Icon: Hash },
  { key: "vectors", label: "Vectors", Icon: Boxes },
];

function StatCard({
  label,
  value,
  Icon,
}: {
  label: string;
  value: number;
  Icon: ComponentType<LucideProps>;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-500">{label}</span>
        <Icon size={16} className="text-gray-400" aria-hidden />
      </div>
      <div
        className="mt-2 text-2xl font-semibold tabular-nums text-gray-900"
        data-testid={`stat-${label.toLowerCase()}`}
      >
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function StatCardsSkeleton() {
  return (
    <div
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
      aria-hidden
    >
      {STAT_CARDS.map((c) => (
        <div
          key={c.key}
          className="h-[88px] animate-pulse rounded-lg border border-gray-200 bg-gray-100"
        />
      ))}
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
    >
      <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Unknown error";
}

function StatsGrid({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {STAT_CARDS.map(({ key, label, Icon }) => (
        <StatCard key={key} label={label} value={stats[key]} Icon={Icon} />
      ))}
    </div>
  );
}

function TopEntities({ entities }: { entities: EntitySummary[] }) {
  if (entities.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
        No entities yet. Index some documents to populate the graph.
      </p>
    );
  }

  // Backend already returns descending by mentions; guard against a zero/NaN
  // max so bar widths stay sane.
  const maxMentions = entities.reduce(
    (max, e) => (e.mentions > max ? e.mentions : max),
    0,
  );

  return (
    <ol className="space-y-1.5" aria-label="top entities">
      {entities.map((entity, i) => {
        const pct =
          maxMentions > 0
            ? Math.max(2, Math.round((entity.mentions / maxMentions) * 100))
            : 0;
        return (
          <li
            key={entity.id}
            className="relative overflow-hidden rounded border border-gray-200 bg-white"
            data-testid="entity-row"
          >
            <div
              className="absolute inset-y-0 left-0 opacity-15"
              style={{ width: `${pct}%`, backgroundColor: ENTITY_COLOR }}
              aria-hidden
            />
            <div className="relative flex items-center justify-between gap-3 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="w-5 shrink-0 text-right text-xs font-medium tabular-nums text-gray-400">
                  {i + 1}
                </span>
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: ENTITY_COLOR }}
                  aria-hidden
                />
                <span
                  className="truncate text-sm font-medium text-gray-900"
                  title={entity.name}
                >
                  {entity.name}
                </span>
                {entity.type && (
                  <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                    {entity.type}
                  </span>
                )}
              </div>
              <span
                className="shrink-0 font-mono text-xs tabular-nums text-gray-600"
                data-testid="entity-mentions"
              >
                {entity.mentions.toLocaleString()}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function StatsPage() {
  const statsQuery = useStats();
  const entitiesQuery = useEntities(20);

  return (
    <div className="mx-auto max-w-5xl p-6">
      <header className="mb-6 flex items-center gap-2">
        <BarChart3 size={22} className="text-gray-700" aria-hidden />
        <h1 className="text-xl font-semibold text-gray-900">Stats</h1>
      </header>

      <section className="mb-8" aria-labelledby="stats-overview-heading">
        <h2
          id="stats-overview-heading"
          className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500"
        >
          Overview
        </h2>
        {statsQuery.isLoading ? (
          <StatCardsSkeleton />
        ) : statsQuery.isError ? (
          <ErrorBanner
            message={`Failed to load stats: ${errorMessage(statsQuery.error)}`}
          />
        ) : statsQuery.data ? (
          <StatsGrid stats={statsQuery.data} />
        ) : null}
      </section>

      <section aria-labelledby="top-entities-heading">
        <h2
          id="top-entities-heading"
          className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500"
        >
          Top Entities
        </h2>
        {entitiesQuery.isLoading ? (
          <div
            className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500"
            aria-busy
          >
            <Loader2 size={16} className="animate-spin" aria-hidden />
            Loading entities…
          </div>
        ) : entitiesQuery.isError ? (
          <ErrorBanner
            message={`Failed to load entities: ${errorMessage(
              entitiesQuery.error,
            )}`}
          />
        ) : (
          <TopEntities entities={entitiesQuery.data ?? []} />
        )}
      </section>
    </div>
  );
}

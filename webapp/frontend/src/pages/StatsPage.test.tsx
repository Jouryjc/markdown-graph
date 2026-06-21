import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EntitySummary, Stats } from "../api/types";
import StatsPage from "./StatsPage";

// Mock the hooks module so the page never touches the network or react-query.
const useStatsMock = vi.fn();
const useEntitiesMock = vi.fn();

vi.mock("../api/hooks", () => ({
  useStats: () => useStatsMock(),
  useEntities: (limit?: number) => useEntitiesMock(limit),
}));

interface QueryStub<T> {
  data?: T;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
}

function statsResult(over: Partial<QueryStub<Stats>>): QueryStub<Stats> {
  return { isLoading: false, isError: false, ...over };
}

function entitiesResult(
  over: Partial<QueryStub<EntitySummary[]>>,
): QueryStub<EntitySummary[]> {
  return { isLoading: false, isError: false, ...over };
}

const SAMPLE_STATS: Stats = {
  documents: 12,
  sections: 34,
  chunks: 567,
  entities: 8,
  tags: 5,
  nodes: 626,
  edges: 1024,
  vectors: 567,
};

const SAMPLE_ENTITIES: EntitySummary[] = [
  { id: "e:alpha", name: "Alpha", type: "concept", mentions: 42 },
  { id: "e:beta", name: "Beta", type: "person", mentions: 17 },
  { id: "e:gamma", name: "Gamma", type: "", mentions: 3 },
];

afterEach(() => {
  vi.clearAllMocks();
});

describe("StatsPage", () => {
  it("renders stat cards with their numbers", () => {
    useStatsMock.mockReturnValue(statsResult({ data: SAMPLE_STATS }));
    useEntitiesMock.mockReturnValue(
      entitiesResult({ data: SAMPLE_ENTITIES }),
    );

    render(<StatsPage />);

    // Each labelled card renders its numeric value (locale-formatted).
    expect(screen.getByTestId("stat-documents")).toHaveTextContent("12");
    expect(screen.getByTestId("stat-sections")).toHaveTextContent("34");
    expect(screen.getByTestId("stat-chunks")).toHaveTextContent("567");
    expect(screen.getByTestId("stat-entities")).toHaveTextContent("8");
    expect(screen.getByTestId("stat-tags")).toHaveTextContent("5");
    expect(screen.getByTestId("stat-nodes")).toHaveTextContent("626");
    expect(screen.getByTestId("stat-edges")).toHaveTextContent("1,024");
    expect(screen.getByTestId("stat-vectors")).toHaveTextContent("567");

    // All eight cards present.
    expect(screen.getAllByText(/^(Documents|Sections|Chunks|Entities|Tags|Nodes|Edges|Vectors)$/)).toHaveLength(8);
  });

  it("renders top entities with names and mention counts in descending order", () => {
    useStatsMock.mockReturnValue(statsResult({ data: SAMPLE_STATS }));
    useEntitiesMock.mockReturnValue(
      entitiesResult({ data: SAMPLE_ENTITIES }),
    );

    render(<StatsPage />);

    const list = screen.getByRole("list", { name: "top entities" });
    const rows = within(list).getAllByTestId("entity-row");
    expect(rows).toHaveLength(3);

    // Names appear in the same (descending-by-mentions) order they were given.
    expect(within(rows[0]).getByText("Alpha")).toBeInTheDocument();
    expect(within(rows[0]).getByTestId("entity-mentions")).toHaveTextContent(
      "42",
    );
    expect(within(rows[1]).getByText("Beta")).toBeInTheDocument();
    expect(within(rows[1]).getByTestId("entity-mentions")).toHaveTextContent(
      "17",
    );
    expect(within(rows[2]).getByText("Gamma")).toBeInTheDocument();
    expect(within(rows[2]).getByTestId("entity-mentions")).toHaveTextContent(
      "3",
    );

    // Mention counts are monotonically non-increasing top-to-bottom.
    const counts = rows.map((row) => {
      const text =
        within(row).getByTestId("entity-mentions").textContent ?? "0";
      return Number(text.replace(/,/g, ""));
    });
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
  });

  it("calls useEntities with a limit of 20", () => {
    useStatsMock.mockReturnValue(statsResult({ data: SAMPLE_STATS }));
    useEntitiesMock.mockReturnValue(entitiesResult({ data: [] }));

    render(<StatsPage />);

    expect(useEntitiesMock).toHaveBeenCalledWith(20);
  });

  it("shows an error banner when stats fail to load", () => {
    useStatsMock.mockReturnValue(
      statsResult({ isError: true, error: new Error("boom") }),
    );
    useEntitiesMock.mockReturnValue(entitiesResult({ data: [] }));

    render(<StatsPage />);

    expect(screen.getByRole("alert")).toHaveTextContent(/boom/);
  });

  it("shows an empty state when there are no entities", () => {
    useStatsMock.mockReturnValue(statsResult({ data: SAMPLE_STATS }));
    useEntitiesMock.mockReturnValue(entitiesResult({ data: [] }));

    render(<StatsPage />);

    expect(screen.getByText(/No entities yet/i)).toBeInTheDocument();
  });

  it("renders loading skeletons while stats are pending", () => {
    useStatsMock.mockReturnValue(statsResult({ isLoading: true }));
    useEntitiesMock.mockReturnValue(entitiesResult({ isLoading: true }));

    render(<StatsPage />);

    // No stat values rendered yet.
    expect(screen.queryByTestId("stat-documents")).toBeNull();
    expect(screen.getByText(/Loading entities/i)).toBeInTheDocument();
  });
});

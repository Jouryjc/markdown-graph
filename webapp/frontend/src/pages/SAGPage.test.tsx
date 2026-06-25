import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type {
  JobStatus,
  SAGSearchRequest,
  SAGSearchResponse,
  SAGStatus,
} from "../api/types";
import SAGPage from "./SAGPage";

// react-force-graph-2d needs a real canvas, which jsdom lacks. Mock GraphCanvas
// to a deterministic div so the page renders without a real canvas.
vi.mock("../components/GraphCanvas", () => ({
  default: ({ nodes }: { nodes: unknown[] }) => (
    <div data-testid="graph-canvas">graph:{nodes.length}</div>
  ),
}));

// Hook test doubles. status/job are queries; build/search are mutations.
let statusData: SAGStatus | undefined;
let jobData: JobStatus | undefined;
const buildMutate = vi.fn<(full: boolean, opts?: unknown) => void>();
const searchMutate = vi.fn<(body: SAGSearchRequest, opts?: unknown) => void>();
let searchState: {
  data: SAGSearchResponse | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
};

vi.mock("../api/hooks", () => ({
  useSagStatus: () => ({ data: statusData, isLoading: statusData == null }),
  useSagBuild: () => ({
    mutate: buildMutate,
    isPending: false,
    isError: false,
    error: null,
  }),
  useSagSearch: () => ({ mutate: searchMutate, ...searchState }),
  useJob: () => ({ data: jobData }),
  useQueryClientInvalidate: () => vi.fn(),
}));

function builtStatus(): SAGStatus {
  return {
    built: true,
    events: 12,
    entities: 7,
    links: 20,
    has_embedder: false,
  };
}

function searchResponse(): SAGSearchResponse {
  return {
    events: [
      {
        event_id: "ev_1",
        title: "Alpha 项目启动",
        summary: "团队启动了 Alpha 项目。",
        content: "完整内容…",
        category: "action",
        keywords: ["alpha", "kickoff"],
        score: 0.91,
        hop: 0,
        chunk_id: "c1",
        source_path: "alpha.md",
        heading_path: "Alpha > Intro",
        entities: [{ id: "e_alice", name: "Alice", type: "person" }],
        connected_via: ["e_alice"],
      },
    ],
    entities: [
      { id: "e_alice", name: "Alice", type: "person" },
      { id: "e_team", name: "Team", type: "group" },
    ],
    graph: {
      nodes: [
        { id: "ev_1", type: "event", meta: {} },
        { id: "e_alice", type: "sag_entity", meta: {} },
      ],
      edges: [{ src: "ev_1", dst: "e_alice", type: "has_entity" }],
    },
    trace: {
      query_entities: ["alice"],
      seed_event_ids: ["ev_1"],
      expanded_event_ids: [],
      ranked_event_ids: ["ev_1"],
    },
  };
}

function blankSearch() {
  return {
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    isSuccess: false,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SAGPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  buildMutate.mockReset();
  searchMutate.mockReset();
  statusData = undefined;
  jobData = undefined;
  searchState = blankSearch();
});

describe("SAGPage", () => {
  it("shows the build button and prompt when the index is not built", () => {
    statusData = {
      built: false,
      events: 0,
      entities: 0,
      links: 0,
      has_embedder: false,
    };
    renderPage();

    expect(screen.getByText(/尚未构建 SAG 索引/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /构建 SAG 索引/ }),
    ).toBeInTheDocument();
  });

  it("triggers postSagBuild when the build button is clicked", () => {
    statusData = {
      built: false,
      events: 0,
      entities: 0,
      links: 0,
      has_embedder: false,
    };
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /构建 SAG 索引/ }));
    expect(buildMutate).toHaveBeenCalledTimes(1);
    expect(buildMutate.mock.calls[0][0]).toBe(false);
  });

  it("shows counts when the index is built", () => {
    statusData = builtStatus();
    renderPage();

    const bar = screen.getByRole("region", { name: "SAG 索引状态" });
    expect(within(bar).getByText("12")).toBeInTheDocument();
    expect(within(bar).getByText("7")).toBeInTheDocument();
    expect(within(bar).getByText("20")).toBeInTheDocument();
  });

  it("submits a SAG search with k and max_hops", () => {
    statusData = builtStatus();
    renderPage();

    fireEvent.change(screen.getByLabelText("SAG Query"), {
      target: { value: "alpha kickoff" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/i }));

    expect(searchMutate).toHaveBeenCalledTimes(1);
    const body = searchMutate.mock.calls[0][0];
    expect(body.query).toBe("alpha kickoff");
    expect(body.k).toBe(8);
    expect(body.max_hops).toBe(2);
  });

  it("renders events and entities as two distinct, separable regions", () => {
    statusData = builtStatus();
    searchState = { ...blankSearch(), data: searchResponse(), isSuccess: true };
    renderPage();

    const eventsRegion = screen.getByRole("region", { name: "Events" });
    const entitiesRegion = screen.getByRole("region", { name: "Entities" });

    // event card content lives only in the Events region
    expect(
      within(eventsRegion).getByText("Alpha 项目启动"),
    ).toBeInTheDocument();
    expect(within(eventsRegion).getByText("alpha")).toBeInTheDocument();

    // entities grouped by type in the Entities panel (distinct block)
    expect(within(entitiesRegion).getByText("person")).toBeInTheDocument();
    expect(within(entitiesRegion).getByText("group")).toBeInTheDocument();
    expect(within(entitiesRegion).getByText("Team")).toBeInTheDocument();

    // the two regions are different DOM nodes
    expect(eventsRegion).not.toBe(entitiesRegion);
  });

  it("renders the hyperedge graph container via the mocked GraphCanvas", () => {
    statusData = builtStatus();
    searchState = { ...blankSearch(), data: searchResponse(), isSuccess: true };
    renderPage();

    expect(screen.getByTestId("graph-canvas")).toBeInTheDocument();
    expect(screen.getByLabelText("SAG 超边图")).toBeInTheDocument();
  });

  it("shows an empty-state message when a search returns no events", () => {
    statusData = builtStatus();
    searchState = {
      ...blankSearch(),
      data: {
        events: [],
        entities: [],
        graph: { nodes: [], edges: [] },
        trace: {
          query_entities: [],
          seed_event_ids: [],
          expanded_event_ids: [],
          ranked_event_ids: [],
        },
      },
      isSuccess: true,
    };
    renderPage();

    expect(screen.getByText("没有找到相关事件。")).toBeInTheDocument();
  });
});

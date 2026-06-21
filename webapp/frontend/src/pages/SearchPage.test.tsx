import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { QueryRequest, QueryResponse } from "../api/types";
import SearchPage from "./SearchPage";

// Capture navigation so we can assert search results route by doc_id (the
// document NODE id), not the human-readable source_path.
const navigate = vi.fn<(to: string) => void>();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

// react-force-graph-2d needs a real canvas, which jsdom lacks. Mock the
// SubgraphPanel's GraphCanvas to a deterministic div so the page renders.
vi.mock("../components/GraphCanvas", () => ({
  default: ({ nodes }: { nodes: unknown[] }) => (
    <div data-testid="graph-canvas">graph:{nodes.length}</div>
  ),
}));

// Mock the api hooks module so no network happens and the mutation is
// controllable. NodeDetailDrawer also imports useNodeDetail from here; provide
// a benign stub for it too.
const mutate = vi.fn<(body: QueryRequest) => void>();
let mockState: {
  data: QueryResponse | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
};

vi.mock("../api/hooks", () => ({
  useQuerySearch: () => ({
    mutate,
    ...mockState,
  }),
  useNodeDetail: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

function makeResponse(): QueryResponse {
  return {
    contexts: [
      {
        chunk_id: "c1",
        text: "Vector hit about alpha.",
        score: 0.91,
        doc_id: "d_alpha",
        source_path: "alpha.md",
        heading_path: "Alpha > Intro",
        from_graph: false,
      },
      {
        chunk_id: "c2",
        text: "Graph-expanded chunk about beta.",
        score: 0.42,
        doc_id: "d_beta",
        source_path: "beta.md",
        heading_path: "Beta > Details",
        from_graph: true,
      },
    ],
    subgraph: {
      nodes: [{ id: "n1", type: "chunk", meta: {} }],
      edges: [],
    },
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SearchPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mutate.mockReset();
  navigate.mockReset();
  mockState = {
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    isSuccess: false,
  };
});

describe("SearchPage", () => {
  it("submits the typed query through the mutation with control values", () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("Query"), {
      target: { value: "what is alpha" },
    });
    fireEvent.click(screen.getByRole("button", { name: /search/i }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const body = mutate.mock.calls[0][0];
    expect(body.query).toBe("what is alpha");
    expect(body.mode).toBe("dual");
    expect(body.k).toBe(8);
  });

  it("does not submit a blank query", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Query"), {
      target: { value: "   " },
    });
    // submit the form directly since the button is disabled for blank input
    fireEvent.submit(screen.getByLabelText("Query").closest("form")!);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("renders ContextCards and the 图扩展 badge for from_graph results", () => {
    mockState.data = makeResponse();
    mockState.isSuccess = true;

    renderPage();

    expect(screen.getByText("Vector hit about alpha.")).toBeInTheDocument();
    expect(
      screen.getByText("Graph-expanded chunk about beta."),
    ).toBeInTheDocument();

    // exactly one 图扩展 badge (only the from_graph context)
    const badges = screen.getAllByText("图扩展");
    expect(badges).toHaveLength(1);

    // both source paths shown
    expect(screen.getByText("alpha.md")).toBeInTheDocument();
    expect(screen.getByText("beta.md")).toBeInTheDocument();

    // subgraph panel rendered with the mocked GraphCanvas
    expect(screen.getByTestId("graph-canvas")).toBeInTheDocument();
  });

  it("opens a search result by doc_id, not source_path", () => {
    mockState.data = makeResponse();
    mockState.isSuccess = true;

    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "alpha.md" }));

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/doc/d_alpha");
  });

  it("shows the loading state while pending", () => {
    mockState.isPending = true;
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("检索中…");
  });

  it("shows the error message on failure", () => {
    mockState.isError = true;
    mockState.error = new Error("embedder unavailable");
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("embedder unavailable");
  });

  it("shows an empty-state message when a successful query has no contexts", async () => {
    mockState.isSuccess = true;
    mockState.data = {
      contexts: [],
      subgraph: { nodes: [], edges: [] },
    };
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("没有找到相关结果。")).toBeInTheDocument(),
    );
  });
});

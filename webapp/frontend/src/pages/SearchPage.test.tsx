import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { QueryMode, QueryRequest, QueryResponse } from "../api/types";
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

// The page calls useQuerySearch() once per scheme (dual, vector, file), always
// in that fixed order. We hand each call its own state from `schemeStates` and
// record every mutate() call so tests can assert how many queries fired and
// with which mode.
interface SchemeState {
  data: QueryResponse | undefined;
  isPending: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
}

const SCHEME_ORDER: QueryMode[] = ["dual", "vector", "file"];

let schemeStates: Record<QueryMode, SchemeState>;
const mutate = vi.fn<(body: QueryRequest, opts?: unknown) => void>();
let callIndex = 0;

vi.mock("../api/hooks", () => ({
  useQuerySearch: () => {
    // Resolve which scheme this call corresponds to by call order within a
    // render. The page always instantiates dual, vector, file in that order.
    const scheme = SCHEME_ORDER[callIndex % SCHEME_ORDER.length];
    callIndex += 1;
    return { mutate, ...schemeStates[scheme] };
  },
  useNodeDetail: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

function blankState(): SchemeState {
  return {
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    isSuccess: false,
  };
}

function successState(response: QueryResponse): SchemeState {
  return {
    data: response,
    isPending: false,
    isError: false,
    error: null,
    isSuccess: true,
  };
}

function dualResponse(): QueryResponse {
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

function vectorResponse(): QueryResponse {
  return {
    contexts: [
      {
        chunk_id: "v1",
        text: "Pure vector hit.",
        score: 0.88,
        doc_id: "d_v",
        source_path: "vec.md",
        heading_path: "Vec",
        from_graph: false,
      },
    ],
    subgraph: { nodes: [], edges: [] },
  };
}

function fileResponse(): QueryResponse {
  return {
    contexts: [
      {
        chunk_id: "file::guide.md::0",
        text: "LLM-selected passage from a real file.",
        score: 1,
        doc_id: "",
        source_path: "guide.md",
        heading_path: "",
        from_graph: false,
      },
    ],
    subgraph: { nodes: [], edges: [] },
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
  callIndex = 0;
  schemeStates = {
    dual: blankState(),
    vector: blankState(),
    file: blankState(),
  };
});

describe("SearchPage", () => {
  it("submits the typed query for the single selected scheme with control values", () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("Query"), {
      target: { value: "what is alpha" },
    });
    fireEvent.click(screen.getByRole("button", { name: /search/i }));

    // Default selection is just "dual" -> one query fires.
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
    fireEvent.submit(screen.getByLabelText("Query").closest("form")!);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("renders a single flat result list + sidebar subgraph for one scheme", () => {
    schemeStates.dual = successState(dualResponse());

    renderPage();

    expect(screen.getByText("Vector hit about alpha.")).toBeInTheDocument();
    expect(
      screen.getByText("Graph-expanded chunk about beta."),
    ).toBeInTheDocument();

    // exactly one 图扩展 badge (only the from_graph context)
    expect(screen.getAllByText("图扩展")).toHaveLength(1);

    expect(screen.getByText("alpha.md")).toBeInTheDocument();
    expect(screen.getByText("beta.md")).toBeInTheDocument();

    // single mode -> sidebar subgraph rendered with the mocked GraphCanvas, and
    // no per-column chrome.
    expect(screen.getByTestId("graph-canvas")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /结果/ })).toBeNull();
  });

  it("opens a search result by doc_id, not source_path", () => {
    schemeStates.dual = successState(dualResponse());

    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "alpha.md" }));

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/doc/d_alpha");
  });

  it("shows the loading state while pending (single scheme)", () => {
    schemeStates.dual = { ...blankState(), isPending: true };
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("检索中…");
  });

  it("shows the error message on failure (single scheme)", () => {
    schemeStates.dual = {
      ...blankState(),
      isError: true,
      error: new Error("embedder unavailable"),
    };
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("embedder unavailable");
  });

  it("shows an empty-state message when a successful query has no contexts", async () => {
    schemeStates.dual = successState({
      contexts: [],
      subgraph: { nodes: [], edges: [] },
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("没有找到相关结果。")).toBeInTheDocument(),
    );
  });

  it("renders one column per selected scheme when multiple are chosen", () => {
    schemeStates.dual = successState(dualResponse());
    schemeStates.vector = successState(vectorResponse());
    schemeStates.file = successState(fileResponse());

    renderPage();

    // Select vector and file in addition to dual via the scheme toggles.
    fireEvent.click(screen.getByRole("checkbox", { name: /vector/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /file/i }));

    const dualCol = screen.getByRole("region", { name: "Dual 结果" });
    const vectorCol = screen.getByRole("region", { name: "Vector 结果" });
    const fileCol = screen.getByRole("region", { name: "File 结果" });

    expect(
      within(dualCol).getByText("Vector hit about alpha."),
    ).toBeInTheDocument();
    expect(within(vectorCol).getByText("Pure vector hit.")).toBeInTheDocument();
    expect(
      within(fileCol).getByText("LLM-selected passage from a real file."),
    ).toBeInTheDocument();

    // Result count chrome per column.
    expect(within(dualCol).getByText(/2 结果/)).toBeInTheDocument();
    expect(within(vectorCol).getByText(/1 结果/)).toBeInTheDocument();
  });

  it("fires one query per selected scheme with the matching mode", () => {
    renderPage();

    fireEvent.click(screen.getByRole("checkbox", { name: /vector/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /file/i }));

    fireEvent.change(screen.getByLabelText("Query"), {
      target: { value: "compare schemes" },
    });
    fireEvent.click(screen.getByRole("button", { name: /search/i }));

    // dual + vector + file selected -> three queries.
    expect(mutate).toHaveBeenCalledTimes(3);
    const modes = mutate.mock.calls.map((c) => c[0].mode).sort();
    expect(modes).toEqual(["dual", "file", "vector"]);
  });

  it("gives each column an independent loading / error / empty state", () => {
    schemeStates.dual = { ...blankState(), isPending: true };
    schemeStates.vector = {
      ...blankState(),
      isError: true,
      error: new Error("vector index missing"),
    };
    schemeStates.file = successState({
      contexts: [],
      subgraph: { nodes: [], edges: [] },
    });

    renderPage();

    fireEvent.click(screen.getByRole("checkbox", { name: /vector/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /file/i }));

    const dualCol = screen.getByRole("region", { name: "Dual 结果" });
    const vectorCol = screen.getByRole("region", { name: "Vector 结果" });
    const fileCol = screen.getByRole("region", { name: "File 结果" });

    expect(within(dualCol).getByRole("status")).toHaveTextContent("检索中…");
    expect(within(vectorCol).getByRole("alert")).toHaveTextContent(
      "vector index missing",
    );
    expect(within(fileCol).getByText("没有找到相关结果。")).toBeInTheDocument();
  });

  it("shows a File-scheme column with its LLM result", () => {
    schemeStates.dual = successState(dualResponse());
    schemeStates.file = successState(fileResponse());

    renderPage();

    fireEvent.click(screen.getByRole("checkbox", { name: /file/i }));

    const fileCol = screen.getByRole("region", { name: "File 结果" });
    expect(
      within(fileCol).getByText("LLM-selected passage from a real file."),
    ).toBeInTheDocument();
    expect(within(fileCol).getByText("guide.md")).toBeInTheDocument();
  });
});

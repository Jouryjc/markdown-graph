import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GraphCanvasProps } from "../components/GraphCanvas";
import type { NodeDetailDrawerProps } from "../components/NodeDetailDrawer";
import type { GraphResponse } from "../api/types";
import { useGraph } from "../api/hooks";
import GraphExplorerPage from "./GraphExplorerPage";

// --- Mocks -----------------------------------------------------------------

// Mock the react-query hooks so we control the graph payload directly and never
// hit the network. useNodeDetail is stubbed to a quiet idle state because the
// drawer mounts it.
vi.mock("../api/hooks", () => ({
  useGraph: vi.fn(),
  useNodeDetail: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
  })),
}));

// Mock the typed client (expand neighbors path); not asserted in these tests
// but imported by the page, so keep it inert.
vi.mock("../api/client", () => ({
  expandGraph: vi.fn(async () => ({ nodes: [], edges: [] })),
}));

// react-force-graph-2d needs a real canvas; replace GraphCanvas with a div that
// lists the node ids/types it was handed so we can assert on filtering.
vi.mock("../components/GraphCanvas", () => ({
  default: ({ nodes }: GraphCanvasProps) => (
    <div data-testid="graph-canvas">
      {nodes.map((n) => (
        <div key={n.id} data-testid="canvas-node" data-type={n.type}>
          {n.id}:{n.type}
        </div>
      ))}
    </div>
  ),
}));

// The drawer pulls in lucide + the (mocked) useNodeDetail; render it as a no-op
// to keep these tests focused on the page's own behavior.
vi.mock("../components/NodeDetailDrawer", () => ({
  default: (_props: NodeDetailDrawerProps) => null,
}));

const mockUseGraph = vi.mocked(useGraph);

function makeResponse(overrides: Partial<GraphResponse> = {}): GraphResponse {
  return {
    nodes: [
      { id: "doc1", type: "document", meta: {} },
      { id: "sec1", type: "section", meta: {} },
      { id: "ent1", type: "entity", meta: {} },
    ],
    edges: [
      { src: "doc1", dst: "sec1", type: "contains" },
      { src: "sec1", dst: "ent1", type: "mentions" },
    ],
    truncated: false,
    total_nodes: 3,
    ...overrides,
  };
}

function setGraphData(resp: GraphResponse): void {
  mockUseGraph.mockReturnValue({
    data: resp,
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useGraph>);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("GraphExplorerPage", () => {
  it("hides nodes of a deselected type", () => {
    setGraphData(makeResponse());
    render(<GraphExplorerPage />);

    // All three node types visible initially.
    expect(screen.getAllByTestId("canvas-node")).toHaveLength(3);

    // Uncheck the "entity" filter.
    const entityCheckbox = screen.getByRole("checkbox", { name: "entity" });
    fireEvent.click(entityCheckbox);

    const remaining = screen.getAllByTestId("canvas-node");
    expect(remaining).toHaveLength(2);
    const types = remaining.map((el) => el.getAttribute("data-type"));
    expect(types).toEqual(["document", "section"]);
    expect(types).not.toContain("entity");

    // Re-checking restores it.
    fireEvent.click(entityCheckbox);
    expect(screen.getAllByTestId("canvas-node")).toHaveLength(3);
  });

  it("shows the truncated notice when the response is truncated", () => {
    setGraphData(
      makeResponse({
        truncated: true,
        total_nodes: 42,
      }),
    );
    render(<GraphExplorerPage />);

    const notice = screen.getByTestId("truncated-notice");
    expect(notice).toBeInTheDocument();
    expect(notice).toHaveTextContent("42");
  });

  it("omits the truncated notice when not truncated", () => {
    setGraphData(makeResponse({ truncated: false }));
    render(<GraphExplorerPage />);

    expect(screen.queryByTestId("truncated-notice")).not.toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import DocumentPage from "./DocumentPage";
import type { DocumentDetail, DocumentSummary } from "../api/types";

// Mock the api hooks module so the page renders without a real QueryClient /
// network. The page consumes useDocuments() and useDocument(id).
const useDocumentsMock = vi.fn();
const useDocumentMock = vi.fn();

vi.mock("../api/hooks", () => ({
  useDocuments: () => useDocumentsMock(),
  useDocument: (id: string | null) => useDocumentMock(id),
}));

const DOCUMENTS: DocumentSummary[] = [
  { id: "alpha", path: "alpha.md", chunk_count: 2 },
  { id: "beta", path: "beta.md", chunk_count: 1 },
];

const DETAIL: DocumentDetail = {
  document: {
    id: "alpha",
    path: "alpha.md",
    frontmatter: { title: "Alpha doc" },
  },
  chunks: [
    {
      id: "alpha#0",
      section_path: "Intro > Overview",
      text: "This is the first chunk of alpha.",
    },
    {
      id: "alpha#1",
      section_path: "Details",
      text: "Second chunk body text.",
    },
  ],
  links: ["beta"],
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/doc/:id" element={<DocumentPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("DocumentPage", () => {
  it("renders the document chunks and an out-link to another document", () => {
    useDocumentsMock.mockReturnValue({
      data: DOCUMENTS,
      isLoading: false,
      isError: false,
    });
    useDocumentMock.mockReturnValue({
      data: DETAIL,
      isLoading: false,
      isError: false,
      isSuccess: true,
      error: null,
    });

    renderAt("/doc/alpha");

    // chunk text renders
    expect(
      screen.getByText("This is the first chunk of alpha."),
    ).toBeInTheDocument();
    expect(screen.getByText("Second chunk body text.")).toBeInTheDocument();

    // breadcrumb pieces from section_path
    expect(screen.getByText("Overview")).toBeInTheDocument();

    // out-link to the linked document points at the correct route
    const outLink = screen.getByRole("link", { name: "beta" });
    expect(outLink).toHaveAttribute("href", "/doc/beta");
  });

  it("shows a 404-style message when the document errors as missing", () => {
    useDocumentsMock.mockReturnValue({
      data: DOCUMENTS,
      isLoading: false,
      isError: false,
    });
    useDocumentMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      isSuccess: false,
      error: new Error("not found"),
    });

    renderAt("/doc/missing");

    expect(screen.getByText(/Failed to load document/i)).toBeInTheDocument();
  });
});

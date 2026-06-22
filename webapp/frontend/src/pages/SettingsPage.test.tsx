import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./SettingsPage";
import type {
  ConfigField,
  ConfigResponse,
  UpdateConfigResponse,
} from "../api/types";

// Mock the api hooks module so the page never touches the network / react-query.
const useConfigMock = vi.fn();
const useUpdateConfigMock = vi.fn();
const useResetConfigMock = vi.fn();

vi.mock("../api/hooks", () => ({
  useConfig: () => useConfigMock(),
  useUpdateConfig: () => useUpdateConfigMock(),
  useResetConfig: () => useResetConfigMock(),
}));

function field(over: Partial<ConfigField> & Pick<ConfigField, "key">): ConfigField {
  return {
    label: over.key,
    type: "string",
    value: "",
    default: "",
    source: "default",
    secret: false,
    high_risk: false,
    applies: "live",
    description: "",
    is_set: false,
    ...over,
  };
}

const CONFIG: ConfigResponse = {
  groups: [
    {
      key: "embedding",
      label: "嵌入 (Embedding)",
      fields: [
        field({
          key: "MDGRAPH_EMBED_MODEL",
          label: "嵌入模型",
          type: "string",
          value: "nomic-embed-text",
          default: "nomic-embed-text",
          source: "default",
          applies: "rebuild",
          description: "嵌入使用的模型名",
          is_set: true,
        }),
        field({
          key: "MDGRAPH_EMBED_API_KEY",
          label: "嵌入 API Key",
          type: "secret",
          value: "ollama",
          default: "ollama",
          source: "default",
          secret: true,
          applies: "rebuild",
          is_set: true,
        }),
      ],
    },
    {
      key: "store",
      label: "嵌入器与存储",
      fields: [
        field({
          key: "MDGRAPH_STORE",
          label: "存储路径",
          type: "string",
          value: "./.mdgraph",
          default: "./.mdgraph",
          source: "default",
          high_risk: true,
          applies: "rebuild",
          is_set: true,
        }),
      ],
    },
    {
      key: "limits",
      label: "上传限制",
      fields: [
        field({
          key: "MDGRAPH_MAX_ARCHIVE_BYTES",
          label: "归档大小上限",
          type: "int",
          value: "52428800",
          default: "52428800",
          source: "default",
          applies: "live",
          is_set: true,
        }),
      ],
    },
  ],
};

interface UpdateMutationStub {
  mutate: ReturnType<typeof vi.fn>;
  isPending: boolean;
  isError: boolean;
  error: unknown;
}

function updateStub(over: Partial<UpdateMutationStub> = {}): UpdateMutationStub {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...over,
  };
}

function resetStub(over: Partial<UpdateMutationStub> = {}): UpdateMutationStub {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...over,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useConfigMock.mockReturnValue({
    data: CONFIG,
    isLoading: false,
    isError: false,
    error: null,
  });
  useUpdateConfigMock.mockReturnValue(updateStub());
  useResetConfigMock.mockReturnValue(resetStub());
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("SettingsPage", () => {
  it("renders grouped fields with labels and source badges", () => {
    renderPage();

    expect(screen.getByTestId("group-embedding")).toBeInTheDocument();
    expect(screen.getByTestId("group-store")).toBeInTheDocument();
    expect(screen.getByTestId("group-limits")).toBeInTheDocument();

    expect(screen.getByText("嵌入模型")).toBeInTheDocument();
    expect(screen.getByText("存储路径")).toBeInTheDocument();

    // Each field carries a source badge.
    expect(
      screen.getAllByTestId("source-default").length,
    ).toBeGreaterThanOrEqual(3);

    // High-risk field is visually flagged.
    expect(screen.getByTestId("high-risk-MDGRAPH_STORE")).toBeInTheDocument();
  });

  it("masks an already-set secret by default", () => {
    renderPage();

    const secret = screen.getByTestId(
      "input-MDGRAPH_EMBED_API_KEY",
    ) as HTMLInputElement;
    // Untouched set secret shows the mask placeholder, not the real value.
    expect(secret.value).toBe("••••••••");
    expect(secret.type).toBe("password");
    expect(secret.value).not.toContain("ollama");
  });

  it("enables save only when dirty and submits only the dirty field", async () => {
    const user = userEvent.setup();
    const update = updateStub();
    useUpdateConfigMock.mockReturnValue(update);

    renderPage();

    const saveButton = screen.getByTestId("save-button");
    expect(saveButton).toBeDisabled();

    const modelInput = screen.getByTestId(
      "input-MDGRAPH_EMBED_MODEL",
    ) as HTMLInputElement;
    await user.clear(modelInput);
    await user.type(modelInput, "bge-m3");

    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    expect(update.mutate).toHaveBeenCalledTimes(1);
    const [values] = update.mutate.mock.calls[0];
    // Only the touched field is submitted; the untouched fields are absent.
    expect(values).toEqual({ MDGRAPH_EMBED_MODEL: "bge-m3" });
    expect(values).not.toHaveProperty("MDGRAPH_EMBED_API_KEY");
    expect(values).not.toHaveProperty("MDGRAPH_MAX_ARCHIVE_BYTES");
  });

  it("shows the rebuild warning banner when the response carries warnings", async () => {
    const user = userEvent.setup();
    const update = updateStub({
      mutate: vi.fn((_values, opts) => {
        const resp: UpdateConfigResponse = {
          config: CONFIG,
          warnings: ["向量维度可能变化，请重建索引。"],
        };
        opts?.onSuccess?.(resp);
      }),
    });
    useUpdateConfigMock.mockReturnValue(update);

    renderPage();

    const modelInput = screen.getByTestId(
      "input-MDGRAPH_EMBED_MODEL",
    ) as HTMLInputElement;
    await user.clear(modelInput);
    await user.type(modelInput, "bge-m3");
    await user.click(screen.getByTestId("save-button"));

    await waitFor(() => {
      expect(screen.getByTestId("rebuild-warning")).toBeInTheDocument();
    });
    expect(screen.getByTestId("rebuild-warning")).toHaveTextContent(
      "向量维度可能变化",
    );
    // Banner links to the upload page so the user can rebuild.
    expect(
      screen.getByRole("link", { name: /前往上传页重建索引/ }),
    ).toHaveAttribute("href", "/upload");
  });

  it("asks for confirmation before saving a high-risk change", async () => {
    const user = userEvent.setup();
    const update = updateStub();
    useUpdateConfigMock.mockReturnValue(update);
    const confirmSpy = vi
      .spyOn(window, "confirm")
      .mockReturnValue(false);

    renderPage();

    const storeInput = screen.getByTestId(
      "input-MDGRAPH_STORE",
    ) as HTMLInputElement;
    await user.clear(storeInput);
    await user.type(storeInput, "./other-store");

    await user.click(screen.getByTestId("save-button"));

    // Confirmation was requested and, because it was declined, no save fired.
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(update.mutate).not.toHaveBeenCalled();

    // Accepting the confirmation proceeds with the save.
    confirmSpy.mockReturnValue(true);
    await user.click(screen.getByTestId("save-button"));
    expect(update.mutate).toHaveBeenCalledTimes(1);
    const [values] = update.mutate.mock.calls[0];
    expect(values).toEqual({ MDGRAPH_STORE: "./other-store" });
  });
});

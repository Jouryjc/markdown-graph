import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import UploadPage from "./UploadPage";
import type {
  IndexReport,
  JobStatus,
  UploadAccepted,
} from "../api/types";

// Mock the api hooks module so the page never touches the network / react-query.
// useUploadArchive -> a mutation stub whose mutate() invokes onSuccess with a
// fixed job_id; useJob -> returns whatever JobStatus the current test queued.
const useUploadArchiveMock = vi.fn();
const useJobMock = vi.fn();

vi.mock("../api/hooks", () => ({
  useUploadArchive: () => useUploadArchiveMock(),
  useJob: (jobId: string | null) => useJobMock(jobId),
}));

const JOB_ID = "job-abc123";

const SAMPLE_REPORT: IndexReport = {
  indexed: 7,
  unchanged: 2,
  removed: 1,
  reclaimed: 3,
  entities: 19,
  errors: [],
};

function doneJob(report: IndexReport = SAMPLE_REPORT): JobStatus {
  return {
    job_id: JOB_ID,
    state: "done",
    phase: "done",
    processed: 7,
    total: 7,
    markdown_files: 9,
    report,
    error: null,
  };
}

function runningJob(): JobStatus {
  return {
    job_id: JOB_ID,
    state: "indexing",
    phase: "indexing",
    processed: 3,
    total: 9,
    markdown_files: 9,
    report: null,
    error: null,
  };
}

function errorJob(message: string): JobStatus {
  return {
    job_id: JOB_ID,
    state: "error",
    phase: "extracting",
    processed: 0,
    total: 0,
    markdown_files: 0,
    report: null,
    error: message,
  };
}

interface UploadMutationStub {
  mutate: ReturnType<typeof vi.fn>;
  isPending: boolean;
  isError: boolean;
  error: unknown;
}

// Build a useUploadArchive stub. mutate() synchronously calls the supplied
// onSuccess with { job_id }, mirroring a resolved upload, and (if provided)
// pumps the progress callback so the upload-% UI has something to show.
function uploadStub(
  over: Partial<UploadMutationStub> = {},
): UploadMutationStub {
  return {
    mutate: vi.fn((vars, opts) => {
      vars?.onProgress?.(0.5);
      const accepted: UploadAccepted = { job_id: JOB_ID };
      opts?.onSuccess?.(accepted);
    }),
    isPending: false,
    isError: false,
    error: null,
    ...over,
  };
}

interface JobQueryStub {
  data?: JobStatus;
  isError: boolean;
  error?: unknown;
}

function jobStub(over: Partial<JobQueryStub> = {}): JobQueryStub {
  return { isError: false, ...over };
}

function makeFile(name: string): File {
  return new File(["dummy archive bytes"], name, {
    type: "application/zip",
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <UploadPage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("UploadPage", () => {
  it("uploads a selected archive then renders the IndexReport and a /graph link on done", async () => {
    const user = userEvent.setup();

    // First render: no job yet (jobId is null inside the component -> useJob
    // gets null and we hand back an empty stub). After mutate fires onSuccess,
    // the component sets jobId and re-renders; from then on useJob returns the
    // done job.
    let jobAvailable = false;
    useJobMock.mockImplementation((jobId: string | null) => {
      if (jobId == null || !jobAvailable) return jobStub();
      return jobStub({ data: doneJob() });
    });

    const upload = uploadStub({
      // Flip the job to "available" the moment mutate runs so the post-success
      // re-render observes the done status.
      mutate: vi.fn((vars, opts) => {
        vars?.onProgress?.(0.5);
        jobAvailable = true;
        opts?.onSuccess?.({ job_id: JOB_ID } satisfies UploadAccepted);
      }),
    });
    useUploadArchiveMock.mockReturnValue(upload);

    renderPage();

    // Select a valid archive via the hidden file input.
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    await user.upload(input, makeFile("notes.zip"));
    expect(screen.getByTestId("selected-file")).toHaveTextContent("notes.zip");

    // Submit.
    await user.click(screen.getByRole("button", { name: /开始上传/ }));

    // mutate was invoked with the chosen file and incremental (full=false).
    expect(upload.mutate).toHaveBeenCalledTimes(1);
    const [vars] = upload.mutate.mock.calls[0];
    expect(vars.file.name).toBe("notes.zip");
    expect(vars.full).toBe(false);

    // On done the report numbers render.
    await waitFor(() => {
      expect(screen.getByTestId("job-done")).toBeInTheDocument();
    });
    expect(screen.getByTestId("report-indexed")).toHaveTextContent("7");
    expect(screen.getByTestId("report-unchanged")).toHaveTextContent("2");
    expect(screen.getByTestId("report-removed")).toHaveTextContent("1");
    expect(screen.getByTestId("report-reclaimed")).toHaveTextContent("3");
    expect(screen.getByTestId("report-entities")).toHaveTextContent("19");

    // The link to the graph view is present and points at /graph.
    const graphLink = screen.getByRole("link", { name: "查看图谱" });
    expect(graphLink).toHaveAttribute("href", "/graph");
  });

  it("shows the build-in-progress message body while the job is still running", async () => {
    const user = userEvent.setup();

    let jobAvailable = false;
    useJobMock.mockImplementation((jobId: string | null) => {
      if (jobId == null || !jobAvailable) return jobStub();
      return jobStub({ data: runningJob() });
    });

    const upload = uploadStub({
      mutate: vi.fn((vars, opts) => {
        vars?.onProgress?.(0.5);
        jobAvailable = true;
        opts?.onSuccess?.({ job_id: JOB_ID } satisfies UploadAccepted);
      }),
    });
    useUploadArchiveMock.mockReturnValue(upload);

    renderPage();

    await user.upload(
      screen.getByTestId("file-input") as HTMLInputElement,
      makeFile("docs.tar.gz"),
    );
    await user.click(screen.getByRole("button", { name: /开始上传/ }));

    // The progress view renders with the indexing label + a determinate bar.
    await waitFor(() => {
      expect(screen.getByTestId("job-progress")).toBeInTheDocument();
    });
    expect(screen.getByTestId("job-state-label")).toHaveTextContent(
      "正在索引文档",
    );
    const bar = screen.getByRole("progressbar", { name: "构建进度" });
    // processed 3 / total 9 -> 33%
    expect(bar).toHaveAttribute("aria-valuenow", "33");

    // No done/error UI yet.
    expect(screen.queryByTestId("job-done")).toBeNull();
    expect(screen.queryByTestId("job-error")).toBeNull();
  });

  it("renders the error message when the job ends in state=error", async () => {
    const user = userEvent.setup();

    let jobAvailable = false;
    useJobMock.mockImplementation((jobId: string | null) => {
      if (jobId == null || !jobAvailable) return jobStub();
      return jobStub({
        data: errorJob("archive contains no markdown (.md/.markdown) files"),
      });
    });

    const upload = uploadStub({
      mutate: vi.fn((_vars, opts) => {
        jobAvailable = true;
        opts?.onSuccess?.({ job_id: JOB_ID } satisfies UploadAccepted);
      }),
    });
    useUploadArchiveMock.mockReturnValue(upload);

    renderPage();

    await user.upload(
      screen.getByTestId("file-input") as HTMLInputElement,
      makeFile("empty.zip"),
    );
    await user.click(screen.getByRole("button", { name: /开始上传/ }));

    await waitFor(() => {
      expect(screen.getByTestId("job-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("job-error")).toHaveTextContent(
      "archive contains no markdown",
    );
    expect(screen.queryByTestId("job-done")).toBeNull();
  });

  it("surfaces a clear message when the upload itself is rejected with 409 (build in progress)", async () => {
    useJobMock.mockReturnValue(jobStub());

    const { ApiError } = await import("../api/client");
    useUploadArchiveMock.mockReturnValue(
      uploadStub({
        isError: true,
        error: new ApiError(409, "a build is already in progress"),
      }),
    );

    renderPage();

    const err = screen.getByTestId("upload-error");
    expect(err).toHaveTextContent("已有构建任务正在进行");
  });

  it("rejects an unsupported file extension without uploading", () => {
    useJobMock.mockReturnValue(jobStub());
    const upload = uploadStub();
    useUploadArchiveMock.mockReturnValue(upload);

    renderPage();

    // fireEvent.change bypasses user-event's `accept`-attribute pre-filtering so
    // the component's own extension validation is the thing under test.
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile("readme.md")] } });

    expect(screen.getByRole("alert")).toHaveTextContent("不支持的文件类型");
    expect(screen.queryByTestId("selected-file")).toBeNull();
    // Submit stays disabled; nothing uploaded.
    expect(screen.getByRole("button", { name: /开始上传/ })).toBeDisabled();
    expect(upload.mutate).not.toHaveBeenCalled();
  });
});

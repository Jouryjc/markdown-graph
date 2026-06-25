import { useCallback, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent, FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  CheckCircle2,
  FileArchive,
  Loader2,
  Upload,
  UploadCloud,
} from "lucide-react";

import { ApiError } from "../api/client";
import { useJob, useUploadArchive } from "../api/hooks";
import type { IndexReport, JobState, JobStatus } from "../api/types";

// Extensions the upload endpoint accepts. Mirrors the backend allow-list.
const ACCEPT = ".zip,.tgz,.tar.gz,.tar";
const ACCEPTED_SUFFIXES = [".zip", ".tar.gz", ".tgz", ".tar"];

function hasAcceptedExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_SUFFIXES.some((suffix) => lower.endsWith(suffix));
}

// Chinese labels for each terminal/intermediate job state. The serving build
// runs through these phases in order.
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
  return "上传失败，请稍后重试。";
}

// Map an ApiError status to a clear, actionable Chinese message for the cases
// the backend deliberately surfaces (busy build / no embedder configured).
function uploadErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return "已有构建任务正在进行，请等待其完成后再试。";
    }
    if (error.status === 503) {
      return "服务未配置 embedder，无法构建索引。请在后端配置 MDGRAPH_EMBEDDER 后重试。";
    }
    if (error.status === 413) {
      return `归档过大，超过服务端限制。${error.message}`;
    }
    if (error.status === 400) {
      return `归档无法被接受：${error.message}`;
    }
  }
  return errorMessage(error);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

interface ReportStatDef {
  key: keyof Pick<
    IndexReport,
    "indexed" | "unchanged" | "removed" | "reclaimed" | "entities"
  >;
  label: string;
}

const REPORT_STATS: ReportStatDef[] = [
  { key: "indexed", label: "已索引" },
  { key: "unchanged", label: "未变化" },
  { key: "removed", label: "已移除" },
  { key: "reclaimed", label: "回收向量" },
  { key: "entities", label: "实体" },
];

function ReportView({ report }: { report: IndexReport }) {
  return (
    <div className="space-y-4">
      <div
        className="grid grid-cols-2 gap-3 sm:grid-cols-5"
        data-testid="report-stats"
      >
        {REPORT_STATS.map(({ key, label }) => (
          <div
            key={key}
            className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
          >
            <div className="text-xs font-medium text-gray-500">{label}</div>
            <div
              className="mt-1 text-2xl font-semibold tabular-nums text-gray-900"
              data-testid={`report-${key}`}
            >
              {report[key].toLocaleString()}
            </div>
          </div>
        ))}
      </div>

      {report.errors.length > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
          data-testid="report-errors"
        >
          <div className="mb-1 font-medium">
            {report.errors.length} 个文件处理出错：
          </div>
          <ul className="space-y-1">
            {report.errors.map((pair, i) => (
              <li key={`${i}:${pair[0] ?? ""}`} className="font-mono text-xs">
                <span className="text-amber-900">{pair[0]}</span>
                {pair[1] ? <span className="text-amber-700"> — {pair[1]}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function JobProgress({ job }: { job: JobStatus }) {
  const label = STATE_LABEL[job.state] ?? job.state;
  const hasTotal = job.total > 0;
  const pct = hasTotal
    ? Math.min(100, Math.round((job.processed / job.total) * 100))
    : 0;

  return (
    <div className="space-y-2" data-testid="job-progress">
      <div className="flex items-center gap-2 text-sm text-gray-700">
        <Loader2 size={16} className="animate-spin text-blue-600" aria-hidden />
        <span data-testid="job-state-label">{label}</span>
        {job.phase ? (
          <span className="text-gray-400">({job.phase})</span>
        ) : null}
        {hasTotal ? (
          <span className="ml-auto font-mono text-xs tabular-nums text-gray-500">
            {job.processed.toLocaleString()} / {job.total.toLocaleString()}
          </span>
        ) : null}
      </div>

      {hasTotal ? (
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-gray-200"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="构建进度"
        >
          <div
            className="h-full rounded-full bg-blue-600 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      ) : (
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-gray-200"
          role="progressbar"
          aria-label="构建进度"
          data-testid="job-progress-indeterminate"
        >
          <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-400" />
        </div>
      )}
    </div>
  );
}

/**
 * Upload page: pick / drop a markdown archive (.zip/.tar/.tar.gz/.tgz), choose
 * incremental vs full rebuild, then POST it to /api/upload. The endpoint returns
 * a job_id which we poll via useJob; progress, the final IndexReport, and any
 * error are all rendered here. No `any`; all states handled explicitly.
 */
export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [full, setFull] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadFraction, setUploadFraction] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [selectError, setSelectError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useUploadArchive();
  const jobQuery = useJob(jobId);
  const job = jobQuery.data ?? null;

  const isUploading = upload.isPending;
  const isPolling =
    jobId != null && (job == null || !TERMINAL_STATES.has(job.state));
  const busy = isUploading || isPolling;

  const selectFile = useCallback((picked: File | null) => {
    setSelectError(null);
    if (picked == null) {
      setFile(null);
      return;
    }
    if (!hasAcceptedExtension(picked.name)) {
      setFile(null);
      setSelectError(
        "不支持的文件类型。请选择 .zip / .tar / .tar.gz / .tgz 归档。",
      );
      return;
    }
    setFile(picked);
  }, []);

  const onInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    selectFile(e.target.files?.[0] ?? null);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    selectFile(e.dataTransfer.files?.[0] ?? null);
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (!busy) setDragOver(true);
  };

  const onDragLeave = () => setDragOver(false);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (file == null || busy) return;

    setUploadFraction(0);
    setJobId(null);
    upload.mutate(
      {
        file,
        full,
        onProgress: (fraction) => setUploadFraction(fraction),
      },
      {
        onSuccess: (accepted) => {
          setUploadFraction(1);
          setJobId(accepted.job_id);
        },
      },
    );
  };

  const uploadPct = Math.round(uploadFraction * 100);

  const jobError = job?.state === "error" ? job.error : null;
  const jobErrorVisible = job?.state === "error";
  const reportVisible = job?.state === "done" && job.report != null;
  const pollError = jobQuery.isError ? jobQuery.error : null;

  const submitDisabled = file == null || busy;

  const dropzoneClass = useMemo(() => {
    const base =
      "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors";
    if (dragOver) return `${base} border-blue-400 bg-blue-50`;
    return `${base} border-gray-300 bg-gray-50 hover:border-gray-400`;
  }, [dragOver]);

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header className="mb-6 flex items-center gap-2">
        <Upload size={22} className="text-gray-700" aria-hidden />
        <h1 className="text-xl font-semibold text-gray-900">上传归档</h1>
      </header>

      <p className="mb-6 text-sm text-gray-600">
        上传一个包含 Markdown 文件的归档（.zip / .tar / .tar.gz / .tgz）。
        服务端会解压并构建索引；构建完成后即可在搜索、图谱与统计页面看到新数据。
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div
          className={dropzoneClass}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          data-testid="dropzone"
        >
          <UploadCloud size={32} className="text-gray-400" aria-hidden />
          <div className="text-sm text-gray-600">
            将归档拖拽到此处，或
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              className="ml-1 font-medium text-blue-600 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              点击选择文件
            </button>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            onChange={onInputChange}
            disabled={busy}
            className="sr-only"
            aria-label="选择归档文件"
            data-testid="file-input"
          />
          {file ? (
            <div
              className="mt-2 flex items-center gap-2 rounded bg-white px-3 py-1.5 text-sm text-gray-800 shadow-sm"
              data-testid="selected-file"
            >
              <FileArchive size={16} className="text-gray-500" aria-hidden />
              <span className="font-medium">{file.name}</span>
              <span className="text-gray-400">({formatBytes(file.size)})</span>
            </div>
          ) : null}
        </div>

        {selectError ? (
          <div
            role="alert"
            className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {selectError}
          </div>
        ) : null}

        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={full}
            onChange={(e) => setFull(e.target.checked)}
            disabled={busy}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            data-testid="full-checkbox"
          />
          <span>全量重建（默认关闭，仅增量更新变化的文档）</span>
        </label>

        <button
          type="submit"
          disabled={submitDisabled}
          className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Upload size={16} aria-hidden />
          {isUploading ? "上传中…" : isPolling ? "构建中…" : "开始上传"}
        </button>
      </form>

      {/* upload progress (the multipart transfer itself) */}
      {isUploading && (
        <section className="mt-6 space-y-2" aria-label="上传进度">
          <div className="flex items-center justify-between text-sm text-gray-700">
            <span>正在上传归档…</span>
            <span
              className="font-mono text-xs tabular-nums text-gray-500"
              data-testid="upload-pct"
            >
              {uploadPct}%
            </span>
          </div>
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-gray-200"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={uploadPct}
            aria-label="上传进度"
          >
            <div
              className="h-full rounded-full bg-blue-600 transition-all"
              style={{ width: `${uploadPct}%` }}
            />
          </div>
        </section>
      )}

      {/* upload rejected by the server (409 / 503 / 413 / 400 / network) */}
      {upload.isError && (
        <div
          role="alert"
          className="mt-6 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          data-testid="upload-error"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>{uploadErrorMessage(upload.error)}</span>
        </div>
      )}

      {/* build job progress + result */}
      {jobId != null && (
        <section className="mt-6 space-y-4" aria-label="构建状态">
          {pollError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span>无法获取构建状态：{errorMessage(pollError)}</span>
            </div>
          )}

          {job && isPolling && <JobProgress job={job} />}

          {jobErrorVisible && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
              data-testid="job-error"
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span>
                构建失败：{jobError ?? "未知错误"}
              </span>
            </div>
          )}

          {reportVisible && job?.report && (
            <div className="space-y-4" data-testid="job-done">
              <div className="flex items-center gap-2 text-sm font-medium text-green-700">
                <CheckCircle2 size={18} aria-hidden />
                构建完成
              </div>

              <ReportView report={job.report} />

              <div className="flex flex-wrap gap-2">
                <Link
                  to="/graph"
                  className="inline-flex items-center rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                >
                  查看图谱
                </Link>
                <Link
                  to="/stats"
                  className="inline-flex items-center rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  查看统计
                </Link>
                <Link
                  to="/"
                  className="inline-flex items-center rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  去搜索
                </Link>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

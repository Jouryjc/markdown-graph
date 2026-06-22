import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  RotateCcw,
  Save,
  Settings,
} from "lucide-react";

import { useConfig, useResetConfig, useUpdateConfig } from "../api/hooks";
import type {
  ConfigField,
  ConfigGroup,
  ConfigResponse,
  ConfigSource,
} from "../api/types";

// Placeholder shown for a secret that is already set but not yet edited. The
// backend defensively ignores any submitted value equal to this string, so it
// can never be written into the overlay as a real value.
const SECRET_MASK = "••••••••";

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "未知错误";
}

const SOURCE_BADGE: Record<ConfigSource, { label: string; className: string }> =
  {
    overlay: {
      label: "已覆盖",
      className: "bg-blue-50 text-blue-700 border-blue-200",
    },
    env: {
      label: "环境变量",
      className: "bg-gray-100 text-gray-600 border-gray-200",
    },
    default: {
      label: "默认值",
      className: "bg-gray-50 text-gray-400 border-gray-200",
    },
  };

function SourceBadge({ source }: { source: ConfigSource }) {
  const def = SOURCE_BADGE[source];
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-xs font-medium ${def.className}`}
      data-testid={`source-${source}`}
    >
      {def.label}
    </span>
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

// A single editable field. `value` is the current draft string; `dirty` marks
// whether the user has touched it (controls the secret mask display). The
// parent owns all state and just receives change notifications.
function FieldRow({
  field,
  value,
  dirty,
  reveal,
  onChange,
  onToggleReveal,
}: {
  field: ConfigField;
  value: string;
  dirty: boolean;
  reveal: boolean;
  onChange: (next: string) => void;
  onToggleReveal: () => void;
}) {
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
  };

  const inputBase =
    "w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50";

  // For a set-but-untouched secret we show the mask placeholder rather than the
  // real value; once the user edits it, `dirty` flips and the real draft shows.
  const isSecret = field.type === "secret";
  const showSecretMask = isSecret && !dirty && field.is_set;
  const displayValue = showSecretMask ? SECRET_MASK : value;

  return (
    <div
      className="flex flex-col gap-1 border-b border-gray-100 py-3 last:border-b-0"
      data-testid={`field-${field.key}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <label
          htmlFor={`config-${field.key}`}
          className="text-sm font-medium text-gray-800"
        >
          {field.label}
        </label>
        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-500">
          {field.key}
        </code>
        <SourceBadge source={field.source} />
        {field.high_risk ? (
          <span
            className="inline-flex items-center gap-1 rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700"
            data-testid={`high-risk-${field.key}`}
          >
            <AlertTriangle size={12} aria-hidden />
            高风险
          </span>
        ) : null}
      </div>

      {field.description ? (
        <p className="text-xs text-gray-500">{field.description}</p>
      ) : null}

      {isSecret ? (
        <div className="relative">
          <input
            id={`config-${field.key}`}
            type={reveal && !showSecretMask ? "text" : "password"}
            value={displayValue}
            onChange={handleChange}
            className={`${inputBase} pr-10 font-mono`}
            autoComplete="off"
            data-testid={`input-${field.key}`}
          />
          <button
            type="button"
            onClick={onToggleReveal}
            className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600"
            aria-label={reveal ? "隐藏" : "显示"}
            data-testid={`toggle-${field.key}`}
          >
            {reveal ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      ) : field.type === "int" ? (
        <input
          id={`config-${field.key}`}
          type="number"
          min={0}
          step={1}
          value={value}
          onChange={handleChange}
          className={`${inputBase} font-mono`}
          data-testid={`input-${field.key}`}
        />
      ) : (
        <input
          id={`config-${field.key}`}
          type="text"
          value={value}
          onChange={handleChange}
          className={`${inputBase} font-mono`}
          autoComplete="off"
          data-testid={`input-${field.key}`}
        />
      )}
    </div>
  );
}

function GroupCard({
  group,
  draft,
  dirtyKeys,
  revealed,
  onChange,
  onToggleReveal,
}: {
  group: ConfigGroup;
  draft: Record<string, string>;
  dirtyKeys: Set<string>;
  revealed: Set<string>;
  onChange: (key: string, next: string) => void;
  onToggleReveal: (key: string) => void;
}) {
  return (
    <section
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      data-testid={`group-${group.key}`}
    >
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-gray-500">
        {group.label}
      </h2>
      <div>
        {group.fields.map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            value={draft[field.key] ?? ""}
            dirty={dirtyKeys.has(field.key)}
            reveal={revealed.has(field.key)}
            onChange={(next) => onChange(field.key, next)}
            onToggleReveal={() => onToggleReveal(field.key)}
          />
        ))}
      </div>
    </section>
  );
}

// Build the initial draft map from a config response. Secret fields start blank
// in the draft (the mask is rendered from `is_set`), everything else seeds with
// its effective value.
function buildDraft(config: ConfigResponse): Record<string, string> {
  const draft: Record<string, string> = {};
  for (const group of config.groups) {
    for (const field of group.fields) {
      draft[field.key] = field.type === "secret" ? "" : field.value;
    }
  }
  return draft;
}

interface SettingsFormProps {
  config: ConfigResponse;
}

/**
 * Editable settings form. Tracks a local `draft` plus a `dirtyKeys` set so only
 * touched fields are submitted. Saving high-risk fields prompts for explicit
 * confirmation; rebuild-class changes surface a warning banner linking to the
 * upload page so the user can rebuild the index.
 */
function SettingsForm({ config }: SettingsFormProps) {
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    buildDraft(config),
  );
  const [dirtyKeys, setDirtyKeys] = useState<Set<string>>(() => new Set());
  const [revealed, setRevealed] = useState<Set<string>>(() => new Set());
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  const update = useUpdateConfig();
  const reset = useResetConfig();

  const fieldsByKey = useMemo(() => {
    const map = new Map<string, ConfigField>();
    for (const group of config.groups) {
      for (const field of group.fields) {
        map.set(field.key, field);
      }
    }
    return map;
  }, [config]);

  const handleChange = (key: string, next: string) => {
    setSaved(false);
    setDraft((prev) => ({ ...prev, [key]: next }));
    setDirtyKeys((prev) => {
      if (prev.has(key)) return prev;
      const nextSet = new Set(prev);
      nextSet.add(key);
      return nextSet;
    });
  };

  const handleToggleReveal = (key: string) => {
    setRevealed((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(key)) {
        nextSet.delete(key);
      } else {
        nextSet.add(key);
      }
      return nextSet;
    });
  };

  const isBusy = update.isPending || reset.isPending;
  const hasDirty = dirtyKeys.size > 0;

  const handleSave = () => {
    if (!hasDirty || isBusy) return;

    // Confirm before persisting any high-risk change (store/embedder).
    const dirtyHighRisk = [...dirtyKeys].filter(
      (key) => fieldsByKey.get(key)?.high_risk,
    );
    if (dirtyHighRisk.length > 0) {
      const labels = dirtyHighRisk
        .map((key) => fieldsByKey.get(key)?.label ?? key)
        .join("、");
      const ok = window.confirm(
        `你正在修改高风险配置（${labels}）。这可能导致已建索引不兼容，需要重建。确认保存？`,
      );
      if (!ok) return;
    }

    // Only submit dirty fields. An empty string for a non-secret falls back to
    // env/default on the backend; secrets that were touched submit the new value.
    const values: Record<string, string | null> = {};
    for (const key of dirtyKeys) {
      values[key] = draft[key];
    }

    update.mutate(values, {
      onSuccess: (resp) => {
        setWarnings(resp.warnings);
        setSaved(true);
        setDirtyKeys(new Set());
        setRevealed(new Set());
        setDraft(buildDraft(resp.config));
      },
    });
  };

  const handleReset = () => {
    if (isBusy) return;
    const ok = window.confirm(
      "确定要清空所有覆盖配置并回落到环境变量/默认值吗？",
    );
    if (!ok) return;
    reset.mutate(undefined, {
      onSuccess: (resp) => {
        setWarnings([]);
        setSaved(false);
        setDirtyKeys(new Set());
        setRevealed(new Set());
        setDraft(buildDraft(resp.config));
      },
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={!hasDirty || isBusy}
          className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="save-button"
        >
          {update.isPending ? (
            <Loader2 size={16} className="animate-spin" aria-hidden />
          ) : (
            <Save size={16} aria-hidden />
          )}
          保存{hasDirty ? `（${dirtyKeys.size}）` : ""}
        </button>
        <button
          type="button"
          onClick={handleReset}
          disabled={isBusy}
          className="inline-flex items-center gap-1.5 rounded border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="reset-button"
        >
          {reset.isPending ? (
            <Loader2 size={16} className="animate-spin" aria-hidden />
          ) : (
            <RotateCcw size={16} aria-hidden />
          )}
          重置为默认
        </button>
      </div>

      {saved ? (
        <div
          role="status"
          className="flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700"
          data-testid="save-success"
        >
          <CheckCircle2 size={16} className="shrink-0" aria-hidden />
          <span>配置已保存并即时生效。</span>
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <div
          role="alert"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700"
          data-testid="rebuild-warning"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
            <div className="space-y-1">
              <ul className="space-y-0.5">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
              <Link
                to="/upload"
                className="inline-block font-medium text-amber-800 underline hover:text-amber-900"
              >
                前往上传页重建索引
              </Link>
            </div>
          </div>
        </div>
      ) : null}

      {update.isError ? (
        <ErrorBanner message={`保存失败：${errorMessage(update.error)}`} />
      ) : null}
      {reset.isError ? (
        <ErrorBanner message={`重置失败：${errorMessage(reset.error)}`} />
      ) : null}

      {config.groups.map((group) => (
        <GroupCard
          key={group.key}
          group={group}
          draft={draft}
          dirtyKeys={dirtyKeys}
          revealed={revealed}
          onChange={handleChange}
          onToggleReveal={handleToggleReveal}
        />
      ))}
    </div>
  );
}

/**
 * Settings page: visualises every env-driven configuration value grouped by
 * concern, lets the user edit and persist them to a local overlay, and warns
 * when a change requires rebuilding the index.
 */
export default function SettingsPage() {
  const configQuery = useConfig();

  return (
    <div className="mx-auto max-w-3xl p-6">
      <header className="mb-6 flex items-center gap-2">
        <Settings size={22} className="text-gray-700" aria-hidden />
        <h1 className="text-xl font-semibold text-gray-900">系统配置</h1>
      </header>

      <p className="mb-6 text-sm text-gray-600">
        在此查看并修改本项目的环境变量配置。保存后绝大多数改动无需重启即时生效；
        影响向量维度或存储位置的改动需要重建索引。
      </p>

      {configQuery.isLoading ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500"
          aria-busy
        >
          <Loader2 size={16} className="animate-spin" aria-hidden />
          正在加载配置…
        </div>
      ) : configQuery.isError ? (
        <ErrorBanner
          message={`无法加载配置：${errorMessage(configQuery.error)}`}
        />
      ) : configQuery.data ? (
        <SettingsForm config={configQuery.data} />
      ) : null}
    </div>
  );
}

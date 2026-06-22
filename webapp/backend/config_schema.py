"""配置元数据 schema — 全部可配置环境变量的单一事实源。

每个 :class:`FieldSpec` 描述一个 env 变量：展示名、类型、默认值（字符串形式，
与 env 一致）、生效方式（``live`` / ``rebuild``）、是否密钥、是否高风险。

默认值复用 ``settings`` 的 ``DEFAULT_*`` 常量与各 provider 模块的内联默认串
（在此以模块常量声明），避免跨层重复定义漂移。前端 ``api/types.ts`` 的配置类型
镜像 GET /api/config 的契约，新增字段只需改本文件。
"""

from __future__ import annotations

from dataclasses import dataclass

from .settings import (
    DEFAULT_EMBEDDER,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_TOTAL_UNCOMPRESSED,
    DEFAULT_STORE,
)

# Provider 模块内联默认串（mdgraph/providers/*）。在此集中声明，测试断言与 provider
# 一致，避免硬编码漂移。
DEFAULT_EMBED_BASE_URL = "http://localhost:11434/v1"
DEFAULT_EMBED_API_KEY = "ollama"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LLM_API_KEY = "ollama"
DEFAULT_LLM_MODEL = "qwen2.5:3b"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"


@dataclass(frozen=True)
class FieldSpec:
    key: str  # 环境变量名，如 "MDGRAPH_EMBED_MODEL"
    group: str  # 组 key，如 "embedding"
    label: str  # 展示名
    type: str  # "string" | "int" | "url" | "secret"
    default: str  # 默认值的字符串形式（int 也存字符串，与 env 一致）
    description: str
    applies: str  # "live" | "rebuild"
    secret: bool = False
    high_risk: bool = False


GROUPS: list[tuple[str, str]] = [  # 决定展示顺序与中文组名
    ("embedding", "嵌入 (Embedding)"),
    ("store", "嵌入器与存储"),
    ("llm", "本地 LLM"),
    ("anthropic", "Anthropic"),
    ("limits", "上传限制"),
]


FIELD_SPECS: list[FieldSpec] = [
    # ---- 嵌入 Embedding ----
    FieldSpec(
        key="MDGRAPH_EMBED_BASE_URL",
        group="embedding",
        label="嵌入服务地址",
        type="url",
        default=DEFAULT_EMBED_BASE_URL,
        description="OpenAI 兼容嵌入端点（默认本地 Ollama）。",
        applies="rebuild",
    ),
    FieldSpec(
        key="MDGRAPH_EMBED_API_KEY",
        group="embedding",
        label="嵌入 API Key",
        type="secret",
        default=DEFAULT_EMBED_API_KEY,
        description="嵌入端点的 API Key（本地 Ollama 用占位值 ollama）。",
        applies="rebuild",
        secret=True,
    ),
    FieldSpec(
        key="MDGRAPH_EMBED_MODEL",
        group="embedding",
        label="嵌入模型",
        type="string",
        default=DEFAULT_EMBED_MODEL,
        description="嵌入模型 id（更换会改变向量维度，需重建索引）。",
        applies="rebuild",
    ),
    # ---- 嵌入器/存储 ----
    FieldSpec(
        key="MDGRAPH_EMBEDDER",
        group="store",
        label="嵌入器 (Embedder)",
        type="string",
        default=DEFAULT_EMBEDDER,
        description="嵌入器 spec（短名 fastembed:/openai: 或 dotted path）。更换会影响向量维度。",
        applies="rebuild",
        high_risk=True,
    ),
    FieldSpec(
        key="MDGRAPH_STORE",
        group="store",
        label="存储目录 (Store)",
        type="string",
        default=DEFAULT_STORE,
        description="图与向量存储目录。更换会切换到不同的索引数据。",
        applies="rebuild",
        high_risk=True,
    ),
    # ---- 本地 LLM ----
    FieldSpec(
        key="MDGRAPH_LLM",
        group="llm",
        label="LLM 抽取器 (Extractor)",
        type="string",
        default="",
        description="实体抽取 provider 的 dotted path（留空=不启用 LLM 抽取）。",
        applies="rebuild",
    ),
    FieldSpec(
        key="MDGRAPH_LLM_BASE_URL",
        group="llm",
        label="LLM 服务地址",
        type="url",
        default=DEFAULT_LLM_BASE_URL,
        description="本地 LLM 的 OpenAI 兼容端点（默认本地 Ollama）。",
        applies="live",
    ),
    FieldSpec(
        key="MDGRAPH_LLM_API_KEY",
        group="llm",
        label="LLM API Key",
        type="secret",
        default=DEFAULT_LLM_API_KEY,
        description="本地 LLM 端点的 API Key（本地 Ollama 用占位值 ollama）。",
        applies="live",
        secret=True,
    ),
    FieldSpec(
        key="MDGRAPH_LLM_MODEL",
        group="llm",
        label="LLM 模型",
        type="string",
        default=DEFAULT_LLM_MODEL,
        description="本地 LLM 抽取使用的模型 id。",
        applies="live",
    ),
    # ---- Anthropic ----
    FieldSpec(
        key="ANTHROPIC_API_KEY",
        group="anthropic",
        label="Anthropic API Key",
        type="secret",
        default="",
        description="Anthropic 官方 API Key。",
        applies="live",
        secret=True,
    ),
    FieldSpec(
        key="ANTHROPIC_AUTH_TOKEN",
        group="anthropic",
        label="Anthropic Auth Token",
        type="secret",
        default="",
        description="Anthropic auth token（与代理端点配合使用，优先于 API Key）。",
        applies="live",
        secret=True,
    ),
    FieldSpec(
        key="ANTHROPIC_BASE_URL",
        group="anthropic",
        label="Anthropic 服务地址",
        type="url",
        default="",
        description="Anthropic 兼容端点（留空=官方）。",
        applies="live",
    ),
    FieldSpec(
        key="ANTHROPIC_MODEL",
        group="anthropic",
        label="Anthropic 模型",
        type="string",
        default=DEFAULT_ANTHROPIC_MODEL,
        description="Anthropic 抽取使用的模型 id。",
        applies="live",
    ),
    # ---- 上传限制 ----
    FieldSpec(
        key="MDGRAPH_MAX_ARCHIVE_BYTES",
        group="limits",
        label="上传包大小上限 (字节)",
        type="int",
        default=str(DEFAULT_MAX_ARCHIVE_BYTES),
        description="单次上传压缩包的最大字节数。",
        applies="live",
    ),
    FieldSpec(
        key="MDGRAPH_MAX_ENTRIES",
        group="limits",
        label="压缩包条目数上限",
        type="int",
        default=str(DEFAULT_MAX_ENTRIES),
        description="压缩包内允许的最大成员数。",
        applies="live",
    ),
    FieldSpec(
        key="MDGRAPH_MAX_TOTAL_UNCOMPRESSED",
        group="limits",
        label="解压总大小上限 (字节)",
        type="int",
        default=str(DEFAULT_MAX_TOTAL_UNCOMPRESSED),
        description="解压后写入磁盘的总字节数上限。",
        applies="live",
    ),
    FieldSpec(
        key="MDGRAPH_MAX_FILE_BYTES",
        group="limits",
        label="单文件大小上限 (字节)",
        type="int",
        default=str(DEFAULT_MAX_FILE_BYTES),
        description="解压后单个文件的最大字节数。",
        applies="live",
    ),
]


FIELDS_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FIELD_SPECS}

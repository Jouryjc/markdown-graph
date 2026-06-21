# mdgraph webapp — 上传压缩包构建知识图谱（后台任务 + 进度轮询）设计文档

- 日期：2026-06-21
- 状态：设计稿（待写实现计划）
- 子项目目录：`webapp/`（仓库根 = `mdgraph` 项目，`pyproject.toml` 已含 `pythonpath=["src"]`）
- 依赖引擎：现有 `mdgraph` 库（`MarkdownGraph` = 结构图 + 向量 + 可选 LLM 实体抽取），**只读式复用其 `build()`，仅在引擎侧追加一个进度回调参数**
- 关联文档：`2026-06-21-mdgraph-webapp-frontend-design.md`（全栈平台基线）；本文是其「同步索引（MVP）」之上的**安全上传 + 后台构建**增量

## 0. 一句话定位

在已有 webapp 之上新增一条**更安全的主索引路径**：用户在浏览器上传一个 markdown 压缩包（zip / tar.gz），后端**安全解压**到临时目录，用一个**隔离的引擎实例**在**后台线程**里构建知识图谱，前端通过**轮询作业状态**看到分阶段进度，构建完成后 `reset_engine()` 让服务单例重新打开、读到新数据。

现有 `POST /api/index`（按服务器本地路径同步构建）**保留**，但上传流是面向浏览器用户的**首选安全入口**：用户不需要、也不应该把任意服务器路径塞进 API，而是上传自己机器上的一份语料。

## 1. 目标与范围

### 1.1 目标

1. 浏览器上传一个压缩归档（`.zip` / `.tar.gz` / `.tgz` / `.tar`），后端**安全**解压其中的 markdown 文件。
2. 用一个**与服务单例隔离**的引擎实例在**后台线程**里 `build()`，全程不阻塞 HTTP 请求线程，不与服务单例共享 sqlite / embedder。
3. 通过**作业状态轮询**（`GET /api/jobs/{job_id}`）向前端报告分阶段进度（extracting / indexing / embedding / extracting_entities / done / error），并在 `indexing` 等阶段给出 `processed/total`。
4. 构建成功后 `reset_engine()`，使后续 `/api/query` `/api/graph` `/api/stats` 读到新构建的数据。
5. **安全是头号目标**：解压面是本特性最高风险点，必须系统性防御 zip-slip / 软链 / 解压炸弹 / 体积与条目数失控 / 非 markdown 文件混入（详见 §6）。
6. 工程纪律：后端测试**全程离线确定性**（Mock provider + tmp 目录 + 内存构造的归档字节，零网络、零真实模型）。

### 1.2 不在本期范围（YAGNI）

明确**不做**，以免过度设计：

- **多 worker / 作业持久化（multi-worker job persistence）**：作业注册表是**单进程内存**结构（dict + Lock）。进程重启即丢失作业记录与进行中的构建。不引入 Redis / Celery / RQ / 数据库作业表。单进程单 worker 假设由 §5 的全局构建锁兜底。
- **断点续传 / 分片上传（resumable / chunked uploads）**：上传是一次性 multipart 请求；中断即失败，用户重传。不实现 tus / Content-Range / 分片合并。
- **病毒扫描（virus scanning）**：不接 ClamAV / 任何 AV 引擎。解压安全靠 §6 的结构性校验（路径、类型、体积、条目数、后缀白名单），而非内容扫毒。
- **认证 / 多租户**：沿用基线假设——本地可信环境，单引擎单例单 store，无登录、无 per-user 隔离。
- **WebSocket / SSE 实时推送**：进度走**轮询**（react-query `refetchInterval`），不引入长连接。

这些都是有意省略；如未来需要，再单独立项。

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Browser /upload 页                                                 │
│  <input type=file> ──XHR(multipart, 上传进度)──► POST /api/upload  │
│  ◄── 202 {job_id}                                                  │
│  useJob(job_id): GET /api/jobs/{id}  每 ~1s 轮询                    │
│   (state ∉ {done,error} 时持续 refetch；done→展示 IndexReport)     │
└───────────────┬───────────────────────────────────────────────────┘
                │  /api/*  (Vite dev proxy → :8000)
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI (prefix /api)                                              │
│  routers/upload.py                                                 │
│   POST /api/upload   ── 校验后缀/大小/embedder/构建锁 ──► 启线程    │
│   GET  /api/jobs/{id} ── 读 jobs 注册表 ──► JobStatus              │
│  jobs.py  (内存注册表 dict+Lock，全局 BUILD LOCK，后台 runner)     │
│  archive.py  (安全解压器：zip-slip/软链/炸弹/白名单防御)          │
│  engine_provider.py  set_engine / reset_engine / require_embedder │
└───────────────┬───────────────────────────────────────────────────┘
                │ 后台线程（隔离引擎实例，不碰服务单例的 sqlite/embedder）
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ mdgraph 引擎                                                       │
│  NEW MarkdownGraph(store_dir, embedder=fresh, llm=fresh)          │
│   .build([extract_dir], root=extract_dir, incremental=…,          │
│          progress=callback)  ──► IndexReport                       │
│   .close()                                                         │
│  构建成功 → engine_provider.reset_engine()（服务单例下次重开读新数据）│
└──────────────────────────────────────────────────────────────────┘
```

设计原则：

- **请求线程永不阻塞构建**：`POST /api/upload` 校验通过后立即 `202` 返回 `job_id`，构建在后台线程跑。
- **构建与服务隔离**：构建用**新建**的 `MarkdownGraph`（独立 embedder / 独立 sqlite 连接），不复用 `get_engine()` 单例，规避「sqlite 连接跨线程」与「embedder 状态争用」。完成后 `reset_engine()` 让服务单例**下次** `get_engine()` 重新打开同一 `store_dir`，读到新数据。
- **同一时刻至多一个构建**：单 store + 全局构建锁，第二个上传得到 `409`。
- **解压器是独立、可单测的纯函数模块**（`archive.py`），不依赖 FastAPI，可用内存字节直接驱动单测。

## 3. 引擎侧改动：`build()` 追加进度回调（唯一的引擎改动）

本特性需要在引擎层做**一个**最小增量：让 `build()` / `StructuralIndexer.index()` 接受一个可选 `progress` 回调，以便后台 runner 把进度映射到作业状态。除此之外引擎语义不变。

### 3.1 回调签名

```python
# 约定的进度回调签名（引擎侧调用，webapp 侧实现）
ProgressFn = Callable[[str, int, int], None]   # progress(phase, current, total)
```

- `phase`：阶段标识，取值 `"indexing" | "embedding" | "extracting_entities"`（与 `index()` 的三段主循环对应；解压阶段 `"extracting"` 由 webapp 侧在调用 `build()` 之前自己发，不经引擎）。
- `current` / `total`：该阶段的进度。`total=0` 表示该阶段无可计数项（如无 embedder / 无 llm）。

### 3.2 引擎内埋点（对照 `src/mdgraph/indexer.py` 的真实流程）

`index()` 的真实顺序是：discover → 逐文档 parse/chunk → 按 content-hash 分流 unchanged/built → reconcile 删除 → `for ctx in built: _build_doc` → links pass → `if vector_store+embedder: _embed_and_store(built)`（**一次批量** embed）→ `if llm: _extract_and_store(built)` → `reclaim_orphans`。据此埋三处：

1. **indexing**：在 `for ctx in built` 主循环里，每构建完一个文档调 `progress("indexing", i+1, len(built))`。这是粒度最细、用户最关心的进度条。
2. **embedding**：`_embed_and_store` 是**单次批量** embed（一次 `embed_texts`），无法逐 chunk 报进度，因此只发两点：进入时 `progress("embedding", 0, n_chunks)`，写完 `progress("embedding", n_chunks, n_chunks)`。`n_chunks` = 待嵌入 chunk 总数。
3. **extracting_entities**：`_extract_and_store` 调 `extract_graph(chunks, llm)`。进入时 `progress("extracting_entities", 0, n_chunks)`，完成时 `progress("extracting_entities", n_chunks, n_chunks)`。若 `llm is None` 则此阶段不发。

回调**必须容错**：引擎用 `try/except` 包裹每次回调调用，回调抛异常**绝不**中断构建（webapp 侧回调内部更新作业状态，理论上不抛，但引擎不能因此变脆）。`progress` 默认 `None`，缺省时引擎行为与现状**逐字节一致**——保证既有 CLI / 测试不受影响。

### 3.3 签名变更落点

- `MarkdownGraph.build(paths, root=None, max_chars=1200, overlap=150, incremental=True, progress=None)`：透传给 `index()`。
- `StructuralIndexer.index(paths, root=None, max_chars=1200, overlap=150, incremental=True, progress=None)`：在 §3.2 三处埋点。
- 引擎侧需补一条离线单测：传一个记录调用序列的假回调，断言 phase 顺序与 `current/total` 单调；并断言 `progress=None` 时不报错（向后兼容）。

## 4. REST 契约

### 4.1 `POST /api/upload`（multipart/form-data）

请求字段：

- `file`：归档文件（必填）。
- `full`：`"true"` / `"false"` 字符串（可选，默认 `"false"` → 增量 `incremental=True`；`"true"` → 全量 `incremental=False`）。

行为与状态码（**校验顺序即此顺序**）：

1. **后缀白名单**：`file.filename` 的小写后缀必须 ∈ `{.zip, .tar.gz, .tgz, .tar}`，否则 `400`。（`.tar.gz` 走双后缀判断。）
2. **上传体积上限**：边读边累计字节，超过 `settings.max_archive_bytes`（默认 ~50MB）立即中止，返回 `413`。**不得**先把整包读进内存再判断——按块（chunk）流式读、流式写入临时归档文件，累计超限即停并删临时文件。
3. **embedder 就绪**：调 `require_embedder()`；无 embedder / 无向量库 → `503`（构建必然要写向量，提前失败）。
4. **构建锁**：若已有构建在跑（全局 BUILD LOCK 被占）→ `409 {detail: "a build is already in progress"}`。
5. 通过以上全部：把归档字节落到一个**全新临时文件**，`uuid4()` 生成 `job_id`，在注册表登记 `state="pending"` 的作业，启动**后台线程**跑 runner（§5），立即返回 `202 {job_id}`。

响应模型 `UploadAccepted`：

```python
class UploadAccepted(BaseModel):
    job_id: str
```

### 4.2 `GET /api/jobs/{job_id}` → `JobStatus`

未知 `job_id` → `404`。

```python
JobState = Literal[
    "pending", "extracting", "indexing",
    "embedding", "extracting_entities", "done", "error",
]

class JobStatus(BaseModel):
    job_id: str
    state: JobState
    phase: str = ""            # 人类可读的当前阶段描述（可与 state 同义或更细）
    processed: int = 0         # 当前阶段已处理项
    total: int = 0             # 当前阶段总项数（0 = 不可计数）
    markdown_files: int = 0    # 解压后发现的 .md 文件数
    report: IndexReport | None = None   # 仅 state="done" 时非空
    error: str | None = None            # 仅 state="error" 时非空
```

- `report` **复用现有** `IndexReport`（schemas.py 既有：`{indexed, unchanged, removed, reclaimed, entities, errors: list[list[str]]}`）。runner 把引擎返回的 `IndexReport` dataclass（`errors` 是 tuple 列表）逐条 `list(e)` 转成 JSON 可序列化形式，与 `routers/index.py` 现有写法一致。
- `state` / `processed` / `total` 由引擎回调（§3）经 runner 写入；`phase` 给前端展示用。

### 4.3 schemas.py 新增（与现有风格一致）

在 `webapp/backend/schemas.py` 追加 `UploadAccepted`、`JobStatus`、`JobState`（Literal），**复用** `IndexReport`。`src/api/types.ts` 逐字段镜像（§7.1）。

## 5. 后台构建作业（`webapp/backend/jobs.py`）

### 5.1 注册表与锁

- **作业注册表**：模块级 `dict[str, JobRecord]` + 一把 `threading.Lock` 保护读写。`JobRecord` 是内存数据类，持有 `state/phase/processed/total/markdown_files/report/error` 及内部字段（临时归档路径、解压目录）。
- **全局构建锁（BUILD LOCK）**：模块级单例锁，**保证同一时刻至多一个构建**。`POST /api/upload` 的 `409` 由「尝试性获取 / 至多一个 active 检查」实现：上传线程先 `BUILD_LOCK.acquire(blocking=False)`，失败即 `409`；成功则把锁的所有权交给后台 runner，由 runner 在 `finally` 里释放。
  - 注意：锁的**获取在请求线程**、**释放在后台线程**，要写清楚交接契约（一个布尔/owner 标记），避免请求线程异常时锁泄漏——若 `acquire` 成功但后续启动线程前抛异常，请求线程必须在自己的 `except` 里释放锁。

### 5.2 runner 步骤（核心）

后台线程入口 `run_build_job(job_id, archive_path, full)`：

1. `state = "extracting"`：调 `archive.safe_extract(archive_path, extract_dir)`（§6）解压到一个**全新临时目录**。返回写出的 markdown 文件数，写入 `job.markdown_files`。
2. **零文件即错误**：若 markdown 文件数为 0 → 抛 `ValueError("no markdown files in archive")`，被外层捕获置 `error`。
3. **隔离引擎构建**：**新建** `MarkdownGraph(settings.store_dir, embedder=_build_embedder(settings), llm=_build_llm(settings))`——embedder / llm 都是**为本次构建新建**的实例，sqlite 连接也是这个新引擎自己的，**不复用服务单例**。理由：服务单例的 sqlite 连接被 `_make_thread_safe` 改成 `check_same_thread=False` 是为「读多写少」的服务场景；构建是重写操作，跨线程共享同一连接 + 共享 embedder 风险大，隔离最干净。
4. 调 `engine.build([extract_dir], root=extract_dir, incremental=not full, progress=cb)`：
   - `root=extract_dir` 使存储的 `source_path` = 归档内相对路径（`_relpath` 行为），图谱里路径干净反映归档布局。
   - `cb(phase, current, total)`：映射 `phase → job.state`（`"indexing"/"embedding"/"extracting_entities"`），`current/total → processed/total`，并加锁更新注册表。
5. `engine.close()`：释放本次构建引擎的 sqlite / 向量库句柄。
6. **切换服务单例**：调 `engine_provider.reset_engine()`——关闭并清空服务单例；下次 `get_engine()` 会用 `settings.store_dir` **重新打开**，从而读到刚写好的新数据。`/api/query` `/api/graph` `/api/stats` 随即生效。
7. `job.report = <序列化的 IndexReport>`；`state = "done"`。

**异常处理**：整个 runner 包在 `try/except Exception as exc`，任何异常（解压违规、构建失败、零文件等）→ `state = "error"`，`error = str(exc)`。

**`finally` 清理**（无论成功失败都执行）：

- 删除临时解压目录（`shutil.rmtree(extract_dir, ignore_errors=True)`）。
- 删除临时归档文件。
- 释放 BUILD LOCK（务必在最外层 `finally`，确保**永远**释放，否则后续上传永久 `409`）。

构建后**磁盘上的解压文件不再需要**：文本已进 sqlite chunks + 向量库，`source_path` 作为字符串持久化。所以清理临时目录是安全的。

### 5.3 状态机

```
pending ──► extracting ──► indexing ──► embedding ──► extracting_entities ──► done
   │            │              │            │                  │
   └────────────┴──────────────┴────────────┴──────────────────┴──► error（任一阶段异常）
```

- `embedding` 仅在有 embedder 时出现（本特性 `require_embedder` 已保证有）。
- `extracting_entities` 仅在配置了 llm 时出现；无 llm 则该阶段被跳过，直接 `done`。

## 6. 安全模型 — 归档解压（`webapp/backend/archive.py`，最高风险面）

**这是本特性的头号风险点。** 解压器是独立模块，对外暴露 `safe_extract(archive_path, dest_dir) -> int`（返回写出的 markdown 文件数）。任何违规 `raise` 一个清晰的错误（`ValueError` 或自定义 `ArchiveError`），由 runner 映射到 `error` / 由 router 在同步校验处映射到 `400`。

### 6.1 格式识别

- `.zip` 用 `zipfile`，`.tar` / `.tar.gz` / `.tgz` 用 `tarfile`。
- 按**后缀**判定为主，必要时辅以 magic（文件头）做防御。损坏 / 非法归档（`zipfile.BadZipFile` / `tarfile.TarError`）→ 清晰错误、**绝不崩溃**。

### 6.2 ZIP-SLIP / 路径穿越（对每个 entry 都查）

逐 entry 名校验，命中任一即拒绝：

- entry 名是**绝对路径**（`os.path.isabs(name)` 或以 `/`、盘符开头）。
- entry 名含 `..` 组件（拆 path 组件后包含 `..`）。
- **最终落点逃逸**：`real = os.path.realpath(os.path.join(dest, name))`，若 `real` 不在 `os.path.realpath(dest)` 之内（用 `os.path.commonpath` / 前缀 + 分隔符判断）→ 拒绝。这是**权威判据**，前两条是快速短路。
- 目录 entry：只在 `dest` 内安全 `makedirs`，不跟随任何外部路径。

### 6.3 TAR 软链 / 硬链 / 特殊文件（tar 专属风险）

- 拒绝任何**非普通文件、非目录**的成员：软链（`issym`）、硬链（`islnk`）、设备（`ischr`/`isblk`）、FIFO（`isfifo`）一律拒绝（软链可指向 `dest` 外，是 tar 的 zip-slip 等价物）。
- **纵深防御**：Python 3.12+ 用 `tarfile` 的 data 过滤器（`extractall(filter="data")` 或逐成员 `tar.extract(member, filter="data")`）。但**绝不**只依赖它——§6.2 的路径判据 + 本节的成员类型判据是手写的、与 Python 版本无关的主防线，data 过滤器只是叠加保险。

### 6.4 解压炸弹与体积 / 条目数上限（全部 settings 可配，给安全默认）

| 限制 | settings 字段 | 默认 | 含义 |
|---|---|---|---|
| 上传包体积 | `max_archive_bytes` | ~50MB | §4.1 流式上传时已先卡一道；解压器再独立校验归档文件大小 |
| 条目总数 | `max_entries` | ~5000 | 归档内成员数超限即拒（防「百万小文件」放大） |
| 解压后总字节 | `max_total_uncompressed` | ~200MB | 累计**实际写出**字节超限即中止 |
| 单文件字节 | `max_file_bytes` | ~5MB | 单个 markdown 写出超限即拒该归档 |

强制要点：

- **条目数**：先看 `len(namelist())` / 成员数；超 `max_entries` 直接拒。
- **绝不只信声明大小**：zip 的 `ZipInfo.file_size`、tar 的 `member.size` 可伪造。先用声明值快速预筛（声明值就超 `max_file_bytes` / 累计超 `max_total_uncompressed` 即拒），**同时**在**实际写入**时按块读、累计真实字节，真实写出超过任一上限立即中止并删半成品。这道「写时封顶」是防膨胀比攻击的关键。
- 累计 `total_written`，每写一块都检查 `total_written <= max_total_uncompressed`，越界即抛。

### 6.5 文件白名单与归一化

- **只解压** 后缀小写 ∈ `{.md, .markdown}` 的文件；其余一律**跳过**（不报错，可选地计 `skipped` 数）。
- **`.markdown` → `.md` 归一化**：`discover()` 只 `rglob("*.md")`，`.markdown` 不会被发现。因此解压器**写盘时**把 `.markdown` 改写为 `.md` 后缀，使引擎能索引到它们。
- **保留相对目录结构**（限定在 `dest` 内），使 `source_path` 反映归档布局。
- 注意 `discover()` 还会按 `resolve()` 后真实路径**去重**——归一化改名后若产生同名 `.md` 冲突（如归档里同目录同时存在 `a.md` 与 `a.markdown`），策略：后写者覆盖前者并记一条 warning（实现层可在 `report.warnings` 或解压返回值里体现），不视为致命错误。

### 6.6 解压入口与返回

- 解压进**调用方提供的全新临时目录**（runner 用 `tempfile.mkdtemp()` 建，`finally` 删）。
- 返回写出的 markdown 文件数（必要时附文件列表）。
- 对损坏 / 非法归档健壮：捕获 `zipfile.BadZipFile` / `tarfile.TarError` → 清晰错误，不抛栈、不留半成品（清理交给 runner 的 `finally`）。

## 7. 前端：上传页

### 7.1 类型镜像（`src/api/types.ts`，逐字段对齐 schemas.py）

```ts
export type JobState =
  | "pending" | "extracting" | "indexing"
  | "embedding" | "extracting_entities" | "done" | "error";

export interface UploadAccepted { job_id: string; }

export interface JobStatus {
  job_id: string;
  state: JobState;
  phase: string;
  processed: number;
  total: number;
  markdown_files: number;
  report: IndexReport | null;   // 复用现有 IndexReport
  error: string | null;
}
```

### 7.2 client.ts

- `uploadArchive(file: File, full: boolean): Promise<UploadAccepted>`：用 **`XMLHttpRequest`**（而非 fetch），以便经 `xhr.upload.onprogress` 暴露**上传进度**（大包上传时给用户百分比）。构造 `FormData`，附 `file` 与 `full`（字符串）。非 2xx 解析 `detail` 抛 `ApiError`（与现有 client 风格一致）。
- `getJob(jobId: string): Promise<JobStatus>`：普通 `request()` GET。

### 7.3 hooks.ts

- `useUploadArchive()`：`useMutation`，`mutationFn: ({file, full}) => uploadArchive(...)`，可选透出上传百分比（通过 mutation 外的局部 state 或回调）。
- `useJob(jobId: string | null)`：`useQuery`，`enabled: !!jobId`，**`refetchInterval`**：当 `data.state ∉ {done, error}` 时返回轮询间隔（~1000ms），否则返回 `false` 停止轮询。

### 7.4 页面与路由

- 新增 `src/pages/UploadPage.tsx`，路由 `/upload`（`App.tsx` 加 `<Route path="/upload" .../>`，`NavBar.tsx` 加链接）。
- 交互流：选文件（拖拽 / `<input type=file accept=".zip,.tar.gz,.tgz,.tar">`）→ 勾选「全量重建」复选框（`full`）→ 上传，显示**上传进度条**（来自 XHR）→ 拿到 `job_id` 后 `useJob` 轮询，显示**构建进度**（`state` + `processed/total` + `markdown_files`）→ `done` 展示 `IndexReport`（indexed / unchanged / removed / reclaimed / entities / errors）并引导去 `/`、`/graph`、`/stats`；`error` 显示 `error` 文案与重试入口。
- 错误态前端文案映射：`409`→「已有构建在进行中，请稍候」；`413`→「文件过大」；`503`→「未配置 embedder，无法构建」；`400`→后端 `detail`（如不支持的后缀 / 解压违规）。

## 8. 文件布局

```
webapp/backend/
  archive.py            # 新增：安全解压器（zip/tar，纯模块，无 FastAPI 依赖）
  jobs.py               # 新增：作业注册表 + BUILD LOCK + runner
  routers/upload.py     # 新增：POST /api/upload + GET /api/jobs/{id}
  schemas.py            # 改：+ UploadAccepted / JobStatus / JobState（复用 IndexReport）
  settings.py           # 改：+ max_archive_bytes / max_entries /
                        #      max_total_uncompressed / max_file_bytes（env 可配，安全默认）
  app.py                # 改：include_router(upload.router)
  engine_provider.py    # 不改（复用 set/reset/require + _build_embedder/_build_llm）
  tests/
    test_archive.py     # 新增：解压器安全单测（见 §9）
    test_upload.py      # 新增：上传 + 作业轮询 API 测试（见 §9）

src/mdgraph/
  engine.py             # 改：build(..., progress=None) 透传
  indexer.py            # 改：index(..., progress=None) + §3.2 三处埋点
  tests/...             # 新增：progress 回调离线单测

webapp/frontend/src/
  api/types.ts          # 改：+ JobState/UploadAccepted/JobStatus
  api/client.ts         # 改：+ uploadArchive(XHR) / getJob
  api/hooks.ts          # 改：+ useUploadArchive / useJob
  pages/UploadPage.tsx  # 新增
  App.tsx               # 改：+ /upload 路由
  components/NavBar.tsx # 改：+ 上传链接
```

### 8.1 settings.py 改动（与现有 dataclass + env 风格一致）

在 `Settings` 追加四个字段，`get_settings()` 从 env 读取并落安全默认：

```python
MDGRAPH_MAX_ARCHIVE_BYTES        # 默认 ~50 * 1024 * 1024
MDGRAPH_MAX_ENTRIES              # 默认 5000
MDGRAPH_MAX_TOTAL_UNCOMPRESSED   # 默认 ~200 * 1024 * 1024
MDGRAPH_MAX_FILE_BYTES           # 默认 ~5 * 1024 * 1024
```

## 9. 离线测试纪律

**铁律：真实模型 / API / 网络绝不进 pytest。** 测试用 Mock provider（`mdgraph.providers.mock` 的 `DeterministicEmbeddingProvider` + `MockLLMProvider`）+ tmp 目录 + **内存构造的归档字节**。运行：`python -m pytest`（**不要**裸 `pytest`，可能命中错误解释器）。后端 API 测试沿用 `webapp/backend/tests/conftest.py` 既有套路（tmp_path 建小 store + `set_engine` + `TestClient`）。

### 9.1 `archive.py` 安全单测（核心，每条都用内存里 in-process 构造的恶意归档）

- **zip-slip**：构造含 `../../evil.md`、绝对路径 entry、`..` 落点逃逸的 zip/tar，断言 `safe_extract` 抛错且 `dest` 外无任何写入。
- **tar 软链 / 硬链 / 设备 / FIFO**：用 `tarfile.TarInfo` 造软链等成员，断言被拒。
- **解压炸弹**：造声明大小巨大但实写为膨胀内容的成员、超 `max_total_uncompressed` 的累计、超 `max_file_bytes` 的单文件、超 `max_entries` 的条目数，逐项断言被拒；并断言**实写封顶**确实在写入中途中止（声明值伪造场景）。
- **白名单 + 归一化**：归档含 `.md` / `.markdown` / `.txt` / `.png`，断言只写出 `.md`（且 `.markdown` 被改写为 `.md`），非白名单被跳过、目录结构保留、返回正确文件数。
- **损坏归档**：喂随机字节 / 截断 zip / 坏 tar，断言抛清晰错误、不崩溃、不留半成品。

### 9.2 上传 + 作业 API 测试

- **happy path**：POST 一个内存构造的合法 zip（含 2~3 个 `.md`）→ `202 {job_id}`；轮询 `GET /api/jobs/{id}` 直到 `state="done"`，断言 `report.indexed`、`markdown_files` 正确，且构建后 `reset_engine` 生效（`/api/stats` 反映新数据）。
  - 测试里如何让后台构建确定性结束：用 Mock provider（瞬时、确定性），并允许 runner 在测试模式下**同步执行**或用「轮询直至终态 + 超时」断言，避免竞态。
- **拒绝路径**：错误后缀 → `400`；超 `max_archive_bytes`（用很小的 env 上限 + 稍大字节）→ `413`；无 embedder（`set_engine` 一个无 embedder 引擎）→ `503`；并发第二个上传命中构建锁 → `409`；未知 `job_id` → `404`。
- **零 markdown**：上传只含 `.txt` 的合法 zip → 作业终态 `error`，`error` 文案含「no markdown files」。
- **清理**：断言成功 / 失败后临时解压目录与临时归档文件均被删（可通过监控 tmp 目录或注入临时根做断言）。

## 10. 验收清单

1. 引擎 `build(..., progress=cb)` 在 indexing / embedding / extracting_entities 三阶段按约定回调；`progress=None` 时与现状逐字节一致（既有测试全绿）。
2. `POST /api/upload`：后缀 / 体积 / embedder / 构建锁四道校验按序生效，合法请求 `202 {job_id}`。
3. `GET /api/jobs/{id}`：状态机推进可观测，`done` 带 `IndexReport`，`error` 带文案，未知 id `404`。
4. `archive.py`：§9.1 全部安全用例通过；`dest` 外零写入；损坏归档不崩。
5. 构建用隔离引擎实例，完成后 `reset_engine()`，`/api/query` `/api/stats` 读到新数据；临时文件全部清理；构建锁始终释放（无 `409` 永久占用）。
6. 前端 `/upload` 页可上传（含上传进度）、轮询构建进度、展示报告 / 错误；`tsc -b && vite build` 通过。
7. 后端 `python -m pytest webapp/backend/tests -v` 全绿，全程离线。

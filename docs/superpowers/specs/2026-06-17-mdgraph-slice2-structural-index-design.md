# mdgraph 切片 2：端到端结构索引 — 设计文档

- 日期：2026-06-17
- 状态：已确认（待写实现计划）
- 父 spec：`docs/superpowers/specs/2026-06-16-markdown-graph-engine-design.md`（§12 切片顺序第 2 项）
- 前置：切片 1（基础层 models / providers / GraphStore / VectorStore）已合并到 main

## 1. 目标与范围

构建 **端到端结构索引（无 LLM）**：任意数量 markdown 文件 → 解析 → 分块 → 结构图谱（Document / Section / Chunk / Tag 节点 + CONTAINS / LINKS_TO / TAGGED 边）→ 落 `GraphStore`。

本切片 `MarkdownGraph.build(paths)` 做**全量结构重建**（正确优先）；每文档照常记录 content-hash，但**增量跳过留到切片 6**。

### 不在本切片范围（YAGNI）

- 语义层 `Entity` 抽取（切片 4）。
- embedding 与向量库写入（切片 3）—— 本切片只写 `GraphStore`，不碰 `VectorStore`。
- 检索 / 图扩展 / RRF（切片 5）。
- CLI 打磨（切片 6）；本切片只提供编程门面 `build()` / `stats()`。

## 2. 新增组件（各单一职责、可独立测试）

| 模块 | 职责 | 依赖 |
|---|---|---|
| `src/mdgraph/ids.py` | 确定性 ID 生成 | hashlib |
| `src/mdgraph/ingest.py` | 发现 / 读取文件 + content-hash | 文件系统 |
| `src/mdgraph/parse.py` | markdown → `ParsedDoc` 结构化模型 | markdown-it-py |
| `src/mdgraph/chunk.py` | 章节 → `Chunk` 列表（标题感知 + 超长切分） | parse 产物 |
| `src/mdgraph/indexer.py` | `StructuralIndexer`：两遍法编排建图落库 | 上述全部 + store |
| `MarkdownGraph` 门面（`src/mdgraph/engine.py`，由 `__init__` 再导出） | `build(paths)` / `stats()` | indexer + store |

### GraphStore 补强（来自切片 1 carry-forward）

在 `src/mdgraph/store/graph_store.py` 上新增：

- `transaction()` 上下文管理器 + 各 `upsert_*` 增加 `commit: bool = True` 参数：索引整文档时 `commit=False` 批量写、退出事务时一次提交（解决逐行 commit 吞吐瓶颈）。
- 读访问器 `list_chunks_by_doc(doc_id) -> list[Chunk]`、`list_documents() -> list[tuple[str, str]]`（返回 `(id, hash)`，为增量与剪枝铺路）。

## 3. ID 方案（无引号、确定性）

`src/mdgraph/ids.py`：

- `doc_id(relpath: str) -> str` = `"d_" + sha256(relpath.encode())[:16]`（hex）
- `section_id(doc_id: str, sec_idx: int) -> str` = `f"{doc_id}_s{sec_idx}"`
- `chunk_id(doc_id: str, sec_idx: int, chunk_idx: int) -> str` = `f"{doc_id}_s{sec_idx}_c{chunk_idx}"`
- `tag_id(name: str) -> str` = `"t_" + sha256(name.lower().encode())[:16]`

全部由 hex / 下划线 / 数字组成 —— 满足切片 1 记下的「chunk_id 须无引号」约束（`VectorStore.delete` 谓词安全）。`relpath` 为相对 index 根的 POSIX 路径，保证跨平台稳定。

## 4. 解析模型 `ParsedDoc`

`parse.parse_document(relpath: str, text: str) -> ParsedDoc`（纯函数，无 I/O）：

```
ParsedDoc {
  relpath: str
  frontmatter: dict           # YAML frontmatter（解析失败则 {} + warning）
  sections: list[ParsedSection]
}
ParsedSection {
  sec_idx: int                # 文档内顺序序号（从 0）
  heading_path: str           # 形如 "Intro > Setup"，分隔符常量 SECTION_PATH_SEP = " > "
  level: int                  # 标题层级（0 = frontmatter 之前/无标题的前导正文）
  parent_idx: int | None      # 父 section 的 sec_idx（用于 Section→Section CONTAINS）
  text: str                   # 该 section 正文（不含子 section）
  char_start: int             # 正文在原文中的起止
  char_end: int
  links: list[ParsedLink]     # 该 section 内的链接
  tags: list[str]             # 该 section 内的 #标签（规范化去 #）
}
ParsedLink {
  raw: str                    # 原始链接文本，用于悬挂记录
  target: str                 # wiki 的目标标题，或 md 的相对路径（去 anchor）
  anchor: str | None          # #heading 部分（去掉 #）
  kind: "wiki" | "md"
  pos: int                    # 链接在原文中的字符位置（用于归属到具体 chunk）
}
```

解析要点：
- 标题层级用 markdown-it-py 的 heading token 构建；`heading_path` 为从根到当前标题的标题文本链。
- wikilink 正则支持 `[[target]]`、`[[target|alias]]`、`[[target#anchor]]`、`[[target#anchor|alias]]`。
- md 链接只取**本地链接**（非 `http(s)://`、非 `mailto:`）；带 `#anchor` 的拆分到 `anchor`；纯 `#anchor`（同文档内跳转）`target` 为空、`anchor` 有值。
- `#标签`：行内 `#word`（word 为 `[\w/-]+`），**排除代码块（fenced/inline code）内**与 markdown 标题行的 `#`。
- 代码块内不扫链接与标签。

## 5. 分块 `chunk.py`

`chunk_sections(parsed: ParsedDoc, max_chars: int = 1200, overlap: int = 150) -> list[Chunk]`：

- **章节为块**：每个 `ParsedSection.text` 默认整体为一个 `Chunk`。
- **超长才切**：`len(text) > max_chars` 时按段落（空行）边界贪心打包到 `max_chars`，相邻窗口带 `overlap` 字符重叠；段落本身超 `max_chars` 时按字符硬切。
- 每个 `Chunk` 记 `doc_id`、`section_path`、`text`、`char_start`/`char_end`（映射回原文绝对偏移）；`id = chunk_id(doc_id, sec_idx, chunk_idx)`。
- 空文本 section（仅标题、无正文）不产出 chunk。

默认值 `max_chars=1200`、`overlap=150` 可由 `build()` 透传配置。

## 6. 建图与数据流（两遍法）

`StructuralIndexer.index(paths) -> IndexReport`：

- **Pass 1（发现+解析）**：`ingest.discover(paths)` 递归找全部 `.md`；逐个 `read_file` 得 `(text, hash, mtime)`，`parse_document` + `chunk_sections`，注册：
  - `title_index`: 文件名 stem（小写）→ doc_id（重名时记冲突，取首个并 warning）
  - `path_index`: 相对 POSIX 路径 → doc_id
  暂存每个文档的 `(Document, ParsedDoc, list[Chunk])`。
- **Pass 2（建图+落库）**：逐文档，在一个 `transaction()` 内：
  1. `delete_document(doc_id)`（清旧，保证无孤儿）；
  2. `upsert_document(Document(... hash, mtime, frontmatter))`；
  3. 插节点：Document、各 Section、各 Chunk、各 Tag（`upsert_node`，`commit=False`）；
  4. 插边：
     - `CONTAINS`：Document→顶层 Section、Section→子 Section（按 `parent_idx`）、Section→其 Chunk；
     - `LINKS_TO`：把每个 `ParsedLink` 归属到**包含其 `pos` 的 Chunk**（落不到则该 section 第一个 chunk），解析目标：wiki 查 `title_index`、md 查 `path_index`；有 `anchor` 时目标定位到对应 Section（按 heading slug 匹配，匹配不到则退到 Document）。解析成功 → `LINKS_TO` 边到目标节点；**解析失败 → 不建边**，把 `raw` 追加到该 Chunk 节点 `meta.unresolved_links`；
     - `TAGGED`：Chunk→Tag（正文标签）、Document→Tag（frontmatter `tags:` 列表）。

`IndexReport { indexed: int, skipped: int, errors: list[tuple[str, str]], unresolved_links: int }`。

**门面**：`MarkdownGraph(store_dir).build(paths, max_chars=1200, overlap=150) -> IndexReport`；`stats()` 透传 `GraphStore.stats()`。

## 7. 错误处理

- 单文件 read/parse 失败：跳过 + 收进 `IndexReport.errors=[(path, err)]`，不拖垮整批。
- frontmatter（YAML）解析失败：当作无 frontmatter + 记 warning（不进 errors）。
- 重名文件 stem 冲突：title_index 取首个 + warning。
- 悬挂链接：记入源 Chunk 节点 `meta.unresolved_links`，计入 `IndexReport.unresolved_links`，非错误。

## 8. 测试策略（TDD）

- **单测**：
  - `ids`：确定性、无引号、stem/路径稳定。
  - `parse`：标题层级与 `heading_path`/`parent_idx`；wikilink 的 alias 与 anchor；md 本地链接相对路径、http/mailto 跳过、纯 `#anchor`；`#标签` 在代码块/标题行内不误判；frontmatter 正常与损坏。
  - `chunk`：章节为块、超长按段落切分 + overlap、char 偏移正确、空 section 不产块。
  - store 补强：`transaction()` 批量提交、`list_chunks_by_doc`、`list_documents`。
- **集成**：2~3 个互链 fixture（含 wiki 链接、md 相对链接、anchor、悬挂链接、frontmatter tags、行内 tag、超长 section）→ `build()` → 断言：节点数/类型、CONTAINS 结构、跨文档 LINKS_TO 命中、悬挂记入 meta、TAGGED 命中、`IndexReport` 字段。用真实 `GraphStore`（tmp_path）。
- **确定性、离线**：本切片无 LLM/embedding，纯结构，天然可重复。

## 9. 建议的任务切分（写计划时细化）

1. `ids.py` + 测试。
2. GraphStore 补强（transaction/批量 + list 访问器）+ 测试。
3. `ingest.py`（discover + read_file/hash）+ 测试。
4. `parse.py`（frontmatter + 标题/section + 链接 + 标签）+ 测试（可能拆 2 个任务）。
5. `chunk.py` + 测试。
6. `indexer.py` 两遍法 + `MarkdownGraph.build/stats` 门面 + 集成测试。

## 10. 实现期发现 / 后续切片注意事项

切片 2 实现完成后沉淀（含实现期对计划的修正）：

### 实现期对计划的修正（已在代码中）
- **链接解析移到 Pass 3**：原计划在 `_build_doc` 事务内建 LINKS_TO；但后处理文档的 `delete_document(target)` 会删掉以其节点为端点的所有边（含早先文档指向它的 LINKS_TO）。改为所有 `_build_doc` 完成后再跑 Pass 3 统一连边，每文档独立事务。
- **Pass-2/Pass-3 错误隔离**：单文档建图失败时记入 `report.errors` 并继续，不拖垮整批。
- **删除 reconcile**：`build()` 在 discovery 后删除"不再被发现"的已存文档（`report.removed`），避免删文件后 rebuild 残留孤儿子树。
- **chunk 参数校验**：`chunk_sections` 对 `max_chars<1` / 非法 `overlap` 抛 `ValueError`（防 `max_chars=0` 死循环）。

### 切片 3（embedding + 向量检索）
- **VectorStore 写入接缝已就绪**：`Chunk` 带 `text`/`char_start`/`char_end`/`section_path` 与无引号 `chunk_id`。切片 3 在 `_build_doc` 落 chunk 处（或事后遍历 `list_chunks_by_doc`）embed `chunk.text` 并写 `(chunk_id, vector)`。
- **跨存储级联删除 + reconcile 合并实现**：`GraphStore.delete_document` 只清图库；切片 3 需让 indexer 在「删除/重建文档」与「reconcile 移除文档」两处都同时清除 VectorStore 对应向量。两者都围绕"按 doc 找到其 chunk_ids 跨库清除"。
- **`stats()` 需扩展**：当前只报图库计数，接入 VectorStore 后补向量计数。
- **`max_chars`/`overlap` 已贯通** `build → index → chunk_sections` 且已校验，embedding 尺寸可配置无需改 API。

### 其它（已知、可接受、记录在案）
- `ingest.discover` 跨多根目录是按输入序拼接（每目录内有序），非全局排序；单根 build 不受影响。
- `.md` 后缀大小写敏感（漏 `.MD`/`.markdown`）。
- 行内 tag 归属到 section 首个 chunk（非按 pos 精确归属）。
- `list_chunks_by_doc` 的 `ORDER BY id` 为字典序（`_c10` < `_c2`）。
- `MarkdownGraph` 未实现 `__enter__/__exit__`，`build()` 异常时不自动 `close()`（库门面可接受）。
- parse 的两套代码屏蔽策略（`_split_sections` 行扫描 fence vs `_mask_code` 正则）在未闭合 fence 等边角可能不一致，但各自局部正确。

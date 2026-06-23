# 本地 LLM 抽取器对畸形 relations 健壮化

## 背景 / 问题

实跑本地 ollama（`qwen2.5:3b`）验证 mdgraph 连通性时发现：`LocalLLMExtractor.extract()`
对一段正常文本返回了**空实体、空关系**，但模型其实正确抽出了 3 个实体。

根因：小模型把 `relations` 输出成**数组三元组**（如 `["Claude", "is a", "product"]`）而非
约定的对象 `{"source":..,"target":..,"type":..}`。代码 `local_llm_extractor.py` 对每个
relation 取 `r["source"]`，对 list 取字符串 key 抛 `TypeError`，撞上 `extract()` 末尾的
兜底 `except Exception` → **连同已正确解析的实体一并丢弃**，整体降级为空。

即：小模型 schema 跟随不稳 + 抽取器兜底过于激进（all-or-nothing），叠加导致信号全损。

## Goal

让 `LocalLLMExtractor.extract()` 在 payload 部分畸形时**尽量保留可用信号**，而不是整段丢弃；
特别地，relations 的畸形不得影响 entities 的产出。连通性与既有降级语义保持不变。

## Requirements

- R1 实体与关系**独立解析**：任一侧的逐条解析异常不得波及另一侧，也不得使整个
  `extract()` 降级为空。坏的单条跳过，好的单条保留。
- R2 `relations` 兼容两种形态：
  - 对象形：`{"source":..,"target":..,"type":..}`（既有，`type` 缺省 → `related_to`）。
  - 数组形：`[source, type, target]`（三元 SVO，匹配观测到的 `["Claude","is a","product"]`）；
    `[source, target]`（二元，`type` 缺省 → `related_to`）。
- R3 `entities` 逐条防御：缺 `name`（或 name 为空）的条目跳过，不抛错；`type`/`description`
  缺省行为不变（`concept` / `""`）。
- R4 单条 relation 无法解析（既非合法对象也非合法数组、或缺 source/target）时跳过该条，
  不影响其余条目与全部实体。
- R5 既有兜底语义保留：当 `_extract_json` 返回 `None`（完全非 JSON / 空）或 chat API 抛错时，
  仍降级为空 `ExtractionResult`（现有测试 `test_extract_malformed_degrades_to_empty`、
  `test_extract_api_error_degrades_to_empty` 必须继续通过）。
- R6 不改变默认端点 / 模型 / env 覆盖契约，不改公开签名（`LocalLLMExtractor`、`extract`）。

## 非目标

- 不为 ollama 新增独立 embedder/extractor 短名（registry 不动）。
- 不引入对模型输出做二次 LLM 修复 / 重试。
- 不改 webapp/CLI 配置层。

## Acceptance Criteria

- [ ] 给定 entities 合法、relations 为数组三元组 `[src, type, tgt]` 的 payload，
      `extract()` 同时产出对应 entities 与 relations。
- [ ] 给定 entities 合法、relations 整体畸形（如混入字符串/缺字段）的 payload，
      `extract()` 仍产出全部 entities，relations 仅保留可解析的条目。
- [ ] 数组二元 `[src, tgt]` → `type=related_to`；对象缺 `type` → `related_to`。
- [ ] entities 中缺 `name` 的条目被跳过，其余 entities 正常产出。
- [ ] `test_extract_malformed_degrades_to_empty`、`test_extract_api_error_degrades_to_empty`、
      以及其余既有测试全部通过。
- [ ] 新增针对 R1–R4 的单元测试（fake client，离线，不触网）。
- [ ] `uv run pytest tests/test_local_llm_extractor.py` 全绿；端到端 `qwen2.5:3b` 实跑能产出
      非空实体（relations 视模型输出而定）。

## Notes

- 轻量任务，保持 PRD-only。
- 解析规则即契约，落在本 PRD 的 Requirements / Acceptance Criteria。
- 数组形 relation 的字段顺序约定为 `[source, type, target]`（SVO），依据是观测到的真实
  `qwen2.5:3b` 输出；该约定在实现注释中需写明。

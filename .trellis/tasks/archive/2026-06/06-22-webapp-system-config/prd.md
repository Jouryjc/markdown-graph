# 前端系统配置页：可视化配置全部环境变量

## Goal

在 webapp 前端新增一个「系统配置 / 设置」页面，让用户可视化地查看并编辑本项目全部环境变量驱动的配置项，保存后持久化到一个覆盖层文件，并让绝大多数改动**无需重启后端即时生效**。目标是让用户不必再去后台手动改 `.env` 或导出环境变量。

## Scope

### In scope（本任务覆盖）

- 后端：配置元数据 schema（单一事实源）、覆盖层读写、启动时加载覆盖层、`/api/config` 读/写/重置接口、热生效（写 `os.environ` + `reset_engine()`）。
- 前端：`/settings` 页面、导航入口、API client/types/hooks、分组表单 UI、密钥掩码、来源徽章、脏值保存、重建警告横幅。
- 前后端测试。

### Out of scope（明确不做）

- 认证 / 多用户权限（本工具按 localhost 单用户假设）。
- CORS origins 配置（当前硬编码，非 env 变量）。
- 自动触发重建索引（仅给出警告 + 指引到上传页；用户手动重建）。
- 国际化框架（沿用现有中英混排硬编码风格）。

## Configurable variables（5 组，17 行字段）

| 组 | 变量 | 类型 | 默认值 | 密钥 | 生效方式 |
|---|---|---|---|---|---|
| 嵌入 Embedding | `MDGRAPH_EMBED_BASE_URL` | url | `http://localhost:11434/v1` | 否 | rebuild |
| 嵌入 Embedding | `MDGRAPH_EMBED_API_KEY` | secret | `ollama` | 是 | rebuild |
| 嵌入 Embedding | `MDGRAPH_EMBED_MODEL` | string | `nomic-embed-text` | 否 | rebuild |
| 嵌入器/存储 | `MDGRAPH_EMBEDDER` | string(高风险) | `mdgraph.providers.fastembed_embedder:FastEmbedProvider` | 否 | rebuild |
| 嵌入器/存储 | `MDGRAPH_STORE` | string(高风险) | `./.mdgraph` | 否 | rebuild |
| 本地 LLM | `MDGRAPH_LLM` | string | （空=不启用） | 否 | rebuild |
| 本地 LLM | `MDGRAPH_LLM_BASE_URL` | url | `http://localhost:11434/v1` | 否 | live |
| 本地 LLM | `MDGRAPH_LLM_API_KEY` | secret | `ollama` | 是 | live |
| 本地 LLM | `MDGRAPH_LLM_MODEL` | string | `qwen2.5:3b` | 否 | live |
| Anthropic | `ANTHROPIC_API_KEY` | secret | （空） | 是 | live |
| Anthropic | `ANTHROPIC_AUTH_TOKEN` | secret | （空） | 是 | live |
| Anthropic | `ANTHROPIC_BASE_URL` | url | （空=官方） | 否 | live |
| Anthropic | `ANTHROPIC_MODEL` | string | `claude-sonnet-4-6` | 否 | live |
| 上传限制 | `MDGRAPH_MAX_ARCHIVE_BYTES` | int | `52428800` | 否 | live |
| 上传限制 | `MDGRAPH_MAX_ENTRIES` | int | `5000` | 否 | live |
| 上传限制 | `MDGRAPH_MAX_TOTAL_UNCOMPRESSED` | int | `209715200` | 否 | live |
| 上传限制 | `MDGRAPH_MAX_FILE_BYTES` | int | `5242880` | 否 | live |

> 生效方式说明：`live` = 保存后 `reset_engine()` 即生效；`rebuild` = 同样即时写入，但因影响向量维度/存储位置，已建索引可能不兼容，需用户重建索引才完全可用，保存时返回 `warnings` 提示。

## Constraints

- 生效优先级：**覆盖层 overlay > 环境变量 env > 默认值 default**。
- 覆盖层文件固定在 `REPO_ROOT/.mdgraph/config.json`，与可配置的 `MDGRAPH_STORE` **解耦**（避免改 store 路径丢配置）；该路径已被 `.gitignore` 的 `.mdgraph/` 覆盖。
- 不得改动 `src/mdgraph/providers/*`、`engine_provider.py` 的现有行为；通过"覆盖层写入 `os.environ` + `reset_engine()`"复用既有读取路径。
- `get_settings()` 当前每次现读 env（无缓存），不得引入会破坏热生效的缓存。
- 密钥明文存于本地 `config.json`；API 可返回真实值，前端默认掩码、可点开查看。设计文档须注明 localhost 单用户安全前提。
- 沿用现有技术栈与代码风格：FastAPI router 模式、Tailwind、React Query、严格 TypeScript（无 `any`）。

## Acceptance Criteria

- [ ] `GET /api/config` 返回分组结构，每项含 `value/default/source/secret/applies/description`；密钥项可被前端识别为 secret。
- [ ] `PUT /api/config` 只接收改动字段，校验通过后写覆盖层 + `os.environ` + `reset_engine()`，并返回新配置；改动 embedder/model/store 时返回 `warnings`。
- [ ] 密钥字段未被编辑时回传不会把密钥覆盖成掩码占位符（即"未改不覆盖"）。
- [ ] `POST /api/config/reset` 清空覆盖层，配置回落 env/默认。
- [ ] 重启后端进程后，已保存的覆盖层自动生效（启动钩子）。
- [ ] 改上传限制（如 `MDGRAPH_MAX_ARCHIVE_BYTES`）保存后，下一次上传即按新值校验，无需重启。
- [ ] 前端 `/settings` 页面：分组展示、按类型渲染输入、密钥掩码+眼睛切换、来源徽章、脏值才可保存、保存成功提示、有 `warnings` 时显示重建横幅并链接到上传页；导航出现「设置」入口。
- [ ] 高风险项（`MDGRAPH_STORE`、`MDGRAPH_EMBEDDER`）有视觉标注与二次确认。
- [ ] 后端 config 路由测试 + 前端 `SettingsPage.test.tsx` 全部通过；现有测试不回归。
- [ ] `ruff` / 类型检查 / `vitest` 均通过。

## Notes

- 本特性跨后端→API→前端三层并新增配置字段集，遵循 `.trellis/spec/guides/cross-layer-thinking-guide.md`：schema 单一事实源、避免各层重复定义、密钥占位符这类"派生状态"集中处理。

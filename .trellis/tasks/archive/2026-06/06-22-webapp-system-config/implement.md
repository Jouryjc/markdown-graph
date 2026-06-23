# 执行计划：前端系统配置页

> 实现通过 Workflow 工具分阶段、多 agent 并行编排。本文件是有序检查清单 + 校验命令 + 回滚点；与 workflow 脚本对应。

## 阶段 0 — 前置确认（已完成）

- [x] 探索现状（前端栈、后端配置、env 清单）。
- [x] 设计稿评审通过。

## 阶段 1 — 后端核心（schema + store + 启动钩子）

并行/顺序：1.1→1.2 可并行起草，1.3 依赖二者。

- [ ] 1.1 `webapp/backend/config_schema.py`：`FieldSpec`、`GROUPS`、`FIELD_SPECS`(17 项)、`FIELDS_BY_KEY`；默认值复用 `settings.DEFAULT_*` 与 provider 默认常量。
- [ ] 1.2 `webapp/backend/config_store.py`：`OVERLAY_PATH`、`load_overlay`、`save_overlay`(原子写)、`effective_value`、`effective_config`、`apply_overlay_to_env`、`update_overlay`、`reset_overlay`。
- [ ] 1.3 `webapp/backend/app.py`：`create_app()` 构引擎前调用 `apply_overlay_to_env(load_overlay())`。

校验：`uv run ruff check webapp/backend` ；`uv run python -c "from webapp.backend.config_schema import FIELD_SPECS; print(len(FIELD_SPECS))"`。

## 阶段 2 — 后端路由

依赖阶段 1。

- [ ] 2.1 `webapp/backend/routers/config.py`：`GET /api/config`、`PUT /api/config`、`POST /api/config/reset`；pydantic `ConfigUpdate`；校验（未知 key/int/url/掩码忽略）；写覆盖层→`reset_engine()`→`warnings`。
- [ ] 2.2 `webapp/backend/app.py`：`include_router(config.router)`。
- [ ] 2.3 若有 schemas 模块（`webapp/backend/schemas.py`）则补充响应模型，保持与现有风格一致。

校验：`uv run ruff check webapp/backend`。

## 阶段 3 — 前端

依赖阶段 2 的契约（类型按 design.md 契约镜像，可与阶段 2 并行）。

- [ ] 3.1 `webapp/frontend/src/api/types.ts`：新增配置相关类型。
- [ ] 3.2 `webapp/frontend/src/api/client.ts`：`getConfig/updateConfig/resetConfig`。
- [ ] 3.3 `webapp/frontend/src/api/hooks.ts`：`useConfig/useUpdateConfig/useResetConfig`。
- [ ] 3.4 `webapp/frontend/src/pages/SettingsPage.tsx`：分组表单、密钥掩码、来源徽章、脏值保存、高风险确认、warnings 横幅。
- [ ] 3.5 `webapp/frontend/src/App.tsx` 加路由；`components/NavBar.tsx` 加「设置」入口。

校验：`cd webapp/frontend && npm run build`（tsc + vite）。

## 阶段 4 — 测试

- [ ] 4.1 后端 `tests/` 新增 config 路由测试（见 design.md §7）。
- [ ] 4.2 前端 `webapp/frontend/src/pages/SettingsPage.test.tsx`。

校验：
- 后端：`uv run pytest tests -q`
- 前端：`cd webapp/frontend && npm run test -- --run`

## 阶段 5 — 质量校验与对抗式复核

- [ ] 5.1 全量校验：`uv run ruff check .` ；`uv run pytest -q` ；`cd webapp/frontend && npm run build && npm run test -- --run`。
- [ ] 5.2 对抗式复核（workflow 内 verify 阶段）：密钥未改不覆盖、覆盖层路径解耦、热生效路径、未破坏现有测试、无 `any`。
- [ ] 5.3 跨层一致性（cross-layer guide）：schema↔TS 类型↔UI 字段三处一致；新增字段无各层重复硬编码。

## 验证命令汇总

```bash
uv run ruff check .
uv run pytest -q
cd webapp/frontend && npm run build && npm run test -- --run
```

## 回滚点

- 阶段 1/2 纯新增文件 + `app.py` 少量改动；回滚即删除新文件、还原 `app.py`。
- 阶段 3 新增前端文件 + `App.tsx`/`NavBar.tsx` 改动；回滚还原这两文件、删 SettingsPage 与 api 增量。
- 覆盖层文件运行期生成于 `.mdgraph/config.json`（gitignored），删除即恢复 env/默认行为。
- 提交前确保 `.env` / `.mdgraph/config.json` 不入库。

## 审查门

- 阶段 2 完成：人工或 verify-agent 确认 API 契约与 design.md 一致。
- 阶段 5 完成：全部 Acceptance Criteria 勾选 + 校验命令通过后才提交。

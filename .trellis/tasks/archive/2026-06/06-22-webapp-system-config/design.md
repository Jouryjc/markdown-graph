# 技术设计：前端系统配置页

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend (React)                                            │
│  SettingsPage  ── useConfig() / useUpdateConfig() ──┐        │
│  NavBar(+设置)                                       │        │
└──────────────────────────────────────────────────────┼──────┘
                                                        │ /api/config
┌──────────────────────────────────────────────────────┼──────┐
│ Backend (FastAPI)                                     ▼      │
│  routers/config.py  GET / PUT / POST(reset)                  │
│        │ reads/writes                                        │
│  config_store.py  ── effective_config / save_overlay         │
│        │ uses schema                                         │
│  config_schema.py  (FIELD_SPECS: 单一事实源)                  │
│        │ apply_overlay_to_env() 写 os.environ                │
│        ▼                                                     │
│  settings.get_settings() (现读 env) + engine_provider        │
│        reset_engine() → 下次 get_engine() 用新值重建          │
└──────────────────────────────────────────────────────────────┘
                         │ 启动时
                  create_app(): apply_overlay_to_env() → build
                         │ 持久化
                  REPO_ROOT/.mdgraph/config.json (overlay)
```

核心思路：**不改动任何 provider / 引擎读取逻辑**。所有配置最终都体现为进程 `os.environ`。配置页 = 读取并展示有效值 → 保存时把覆盖层落盘并写入 `os.environ` → `reset_engine()`，下一次请求时 `get_engine()`/`get_settings()` 现读到新值。

## 2. 数据模型与契约（单一事实源）

`webapp/backend/config_schema.py`：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FieldSpec:
    key: str            # 环境变量名，如 "MDGRAPH_EMBED_MODEL"
    group: str          # 组 key，如 "embedding"
    label: str          # 展示名
    type: str           # "string" | "int" | "url" | "secret"
    default: str        # 默认值的字符串形式（int 也存字符串，与 env 一致）
    description: str
    applies: str        # "live" | "rebuild"
    secret: bool = False
    high_risk: bool = False

GROUPS = [  # 决定展示顺序与中文组名
    ("embedding", "嵌入 (Embedding)"),
    ("store",     "嵌入器与存储"),
    ("llm",       "本地 LLM"),
    ("anthropic", "Anthropic"),
    ("limits",    "上传限制"),
]

FIELD_SPECS: list[FieldSpec] = [ ... 17 项，见 prd.md 表 ... ]

FIELDS_BY_KEY = {f.key: f for f in FIELD_SPECS}
```

默认值集中复用 `settings.py` 的 `DEFAULT_*` 常量（`DEFAULT_STORE`、`DEFAULT_EMBEDDER`、`DEFAULT_MAX_*`）以及各 provider 模块的默认串，避免重复定义漂移；provider 默认值（如 `http://localhost:11434/v1`、`nomic-embed-text`）在 schema 内以常量声明并在测试中断言与 provider 模块一致。

### API 契约（前后端共享，TS 类型镜像）

```
GET /api/config →
{
  "groups": [
    { "key": "embedding", "label": "嵌入 (Embedding)",
      "fields": [
        { "key": "MDGRAPH_EMBED_MODEL", "label": "...", "type": "string",
          "value": "nomic-embed-text", "default": "nomic-embed-text",
          "source": "default" | "env" | "overlay",
          "secret": false, "high_risk": false,
          "applies": "rebuild", "description": "...", "is_set": true }
      ] }
  ]
}

PUT /api/config
  body: { "values": { "MDGRAPH_EMBED_MODEL": "bge-m3", "MDGRAPH_STORE": null } }
        # 只含改动项；null = 从覆盖层移除该项（回落 env/默认）
  → 200 { "config": <同 GET 结构>, "warnings": ["..."] }
  → 422 { "detail": [{ "key": "...", "error": "..." }] }   # 校验失败

POST /api/config/reset → 200 { "config": <同 GET 结构> }
```

**密钥处理约定**：
- `GET` 对 secret 字段返回 `value` 为真实明文（localhost 单用户前提），外加 `is_set` 标识是否非空。前端默认掩码渲染、眼睛图标切换明文。
- `PUT` 只接收前端"脏字段"。前端规则：secret 输入框初始为空且标记"未改"；用户输入后才进入脏集合。后端**额外防御**：忽略 value 等于掩码占位串（如 `"••••••••"`）的字段，绝不把掩码写进覆盖层。

## 3. 覆盖层存储 `config_store.py`

```python
OVERLAY_PATH = REPO_ROOT / ".mdgraph" / "config.json"  # 固定，与 MDGRAPH_STORE 解耦

def load_overlay() -> dict[str, str]: ...       # 文件不存在→{}；坏 JSON→{} 并不抛
def save_overlay(values: dict[str, str]) -> None: ...  # 原子写（写 tmp 再 rename），父目录 mkdir
def effective_value(spec) -> tuple[str, source]:  # overlay>env>default，返回值+来源
def effective_config() -> list[group dict]:      # 供 GET 用，secret 也带真实值
def apply_overlay_to_env(overlay: dict) -> None: # 把覆盖层 set 进 os.environ
def update_overlay(changes: dict[str, str|None]) -> dict:  # 合并 changes（None=del）→落盘→应用
```

写覆盖层时只存"用户显式设过的项"。`None` 代表删除该键（回落）。`apply_overlay_to_env` 仅 set 覆盖层中存在的键；不主动 unset 其它键（避免误删进程已有 env）。reset 时：清空 overlay 文件，并对覆盖层曾设过的键执行 `os.environ.pop`（仅 pop 我们写过的、且与当前 env 相等的键，保守处理）。

## 4. 后端路由 `routers/config.py`

- 复用现有 router 注册方式（`app.py` 的 `create_app()` 里 `include_router`）。
- `GET /api/config`：`return {"groups": effective_config()}`。
- `PUT /api/config`：
  1. pydantic 模型 `ConfigUpdate(values: dict[str, str | None])`。
  2. 校验：未知 key → 422；`int` 类型非正整数 → 422；`url` 类型空串放过（表示回落/清空）、非空做基本 `http(s)://` 前缀校验；忽略等于掩码串的 secret。
  3. `update_overlay(changes)`（落盘 + 写 env）。
  4. `reset_engine()`（来自 `engine_provider`）。
  5. 计算 `warnings`：若改动键的 `applies=="rebuild"`（embedder/model/store），加一条"向量维度/存储位置可能变化，请到上传页重建索引"。
  6. `return {"config": effective_config(), "warnings": warnings}`。
- `POST /api/config/reset`：清覆盖层 → `reset_engine()` → 返回 config。
- 并发：与后台构建锁的关系——保存仅写文件 + 写 env + reset_engine；构建线程本就 `get_settings()` 现读，天然拿到新值。不引入新锁；若担心写文件竞争，`save_overlay` 用原子 rename 即可。

## 5. 启动钩子（`app.py`）

在 `create_app()` 构造引擎之前调用 `apply_overlay_to_env(load_overlay())`，使已存在的覆盖层在新进程自动生效。该调用幂等、无副作用（仅 set env）。

## 6. 前端设计

### 6.1 API 层
- `api/types.ts`：新增 `ConfigFieldType`、`ConfigSource`、`ConfigField`、`ConfigGroup`、`ConfigResponse`、`UpdateConfigRequest`、`UpdateConfigResponse`。严格类型，无 `any`。
- `api/client.ts`：新增 `getConfig()`(GET)、`updateConfig(values)`(PUT)、`resetConfig()`(POST)。复用现有 `request<T>()` 封装与 `ApiError`。
- `api/hooks.ts`：`useConfig()`(useQuery)、`useUpdateConfig()`(useMutation，成功后 `invalidateQueries(['config'])`)、`useResetConfig()`。

### 6.2 页面 `pages/SettingsPage.tsx` + 路由
- `App.tsx` 加 `<Route path="/settings" element={<SettingsPage/>} />`。
- `NavBar.tsx` 加一项「设置」（lucide `Settings` 图标），沿用现有 NavLink 激活态样式。
- 结构：顶部标题 + 保存/重置按钮区（保存仅在有脏字段时可点）；按 `groups` 渲染分组卡片；保存成功 toast；`warnings` 非空时顶部黄色横幅，含跳转 `/upload` 的链接。
- 字段渲染（按 `type`）：
  - `string`/`url`/`int` → 文本/number input（int 限制 `min`/整数）。
  - `secret` → password input + 眼睛切换显隐；初始展示掩码占位（来自 `is_set`），聚焦编辑才进入脏集合。
  - 每项：label、描述（灰字小号）、来源徽章（`overlay`=蓝 / `env`=灰 / `default`=浅灰）、`high_risk` 红色「高风险」标签。
- 脏值跟踪：本地 `useState` 维护 `draft` 与 `dirtyKeys`；保存时仅提交 `dirtyKeys` 对应值；`high_risk` 字段被改动则保存前弹二次确认（`window.confirm` 或内联确认区）。
- 状态：loading / error（沿用现有页面的 `AlertCircle` + 文案模式）。

### 6.3 样式
沿用现有 Tailwind 约定：卡片 `border border-gray-200 bg-white p-4`、输入 `border-gray-300 focus:border-blue-500 focus:ring-1`、主按钮 `bg-blue-600 hover:bg-blue-700 disabled:opacity-50`、警告 `border-amber-200 bg-amber-50 text-amber-700`。不引入新组件库。

## 7. 测试

### 后端（`tests/`，沿用现有 webapp 测试用的 TestClient / fixture 模式）
- `GET /api/config` 结构与分组顺序、default 来源标注正确。
- `PUT` 写覆盖层并落盘到临时 OVERLAY_PATH（通过 monkeypatch 指向 tmp）、`os.environ` 被更新、`reset_engine` 被调用（spy/monkeypatch）。
- secret "未改不覆盖"：提交掩码占位串不写入覆盖层。
- int/url 校验 422。
- 改 `MDGRAPH_EMBED_MODEL` 返回 `warnings` 非空；改 `MDGRAPH_MAX_ARCHIVE_BYTES` 无 rebuild 警告。
- `reset` 清空覆盖层、值回落。
- 上传限制端到端：保存新 `MDGRAPH_MAX_ARCHIVE_BYTES` 后 `get_settings()` 现读为新值。
- 启动钩子：预置 overlay 文件 → `apply_overlay_to_env` 后 `os.environ` 命中。

### 前端（`SettingsPage.test.tsx`，沿用 vitest + @testing-library + mock fetch/hooks）
- 渲染分组与字段、secret 默认掩码。
- 改字段 → 保存按钮可用 → 调用 updateConfig 仅带脏字段。
- 响应带 warnings → 显示重建横幅。
- high_risk 字段改动触发确认。

## 8. 风险与权衡

- **明文密钥**：localhost 单用户工具，明确接受；文件已 gitignore。若日后要部署需加认证 + 加密，超出本任务。
- **os.environ 全局可变**：单进程本地工具可接受；与现有"providers 直接读 env"的设计一致，反而是最小侵入做法。
- **rebuild 类改动不自动重建**：YAGNI，给警告 + 指引；自动重建留待后续。
- **覆盖层与 .env 双源**：覆盖层优先，文档说明；用户在 UI 改后，`.env` 不再是有效值来源（除非删除覆盖层对应项）。

## 9. 不做（YAGNI）

认证、加密存储、CORS 配置、自动重建、配置版本/历史、导入导出、i18n 框架。

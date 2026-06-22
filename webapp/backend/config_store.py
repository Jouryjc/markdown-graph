"""覆盖层（overlay）读写 + 有效配置计算。

覆盖层是用户在配置页显式设过的项，落盘到固定路径
``REPO_ROOT/.mdgraph/config.json``（与可配置的 ``MDGRAPH_STORE`` 解耦，
避免改 store 路径丢配置）。生效优先级：overlay > env > default。

热生效思路：所有配置最终都体现为进程 ``os.environ``——保存时把覆盖层写进
``os.environ`` 并 ``reset_engine()``，下一次 ``get_settings()`` / ``get_engine()``
现读到新值。本模块只负责覆盖层与 env 的同步，不触碰任何 provider / 引擎逻辑。
"""

from __future__ import annotations

import json
import os
from typing import Any

from .config_schema import FIELD_SPECS, GROUPS, FieldSpec
from .settings import REPO_ROOT

# 固定路径，与 MDGRAPH_STORE 解耦；.mdgraph/ 已被 .gitignore 覆盖。
OVERLAY_PATH = REPO_ROOT / ".mdgraph" / "config.json"

# 密钥掩码占位串：前端展示密钥时用它代替明文，提交时若 value 等于它视为"未改"。
SECRET_MASK = "••••••••"

# 我们曾写进 os.environ 的键，用于删除 / reset 时保守地只 pop 自己写过的键。
_applied_keys: set[str] = set()


def load_overlay() -> dict[str, str]:
    """读取覆盖层文件。文件不存在 / 坏 JSON / 非 dict 一律返回 {} 且不抛。"""
    try:
        raw = OVERLAY_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # 只保留 str->str 的项，过滤异常类型。
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def save_overlay(values: dict[str, str]) -> None:
    """原子写覆盖层：先写 .tmp 再 os.replace；父目录按需创建。"""
    OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OVERLAY_PATH.with_suffix(OVERLAY_PATH.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_path, OVERLAY_PATH)


def effective_value(spec: FieldSpec) -> tuple[str, str]:
    """返回 (有效值, 来源)。来源 ∈ {'overlay','env','default'}，优先级 overlay>env>default。"""
    overlay = load_overlay()
    if spec.key in overlay:
        return overlay[spec.key], "overlay"
    env_val = os.environ.get(spec.key)
    if env_val is not None:
        return env_val, "env"
    return spec.default, "default"


def _field_dict(spec: FieldSpec) -> dict[str, Any]:
    value, source = effective_value(spec)
    return {
        "key": spec.key,
        "label": spec.label,
        "type": spec.type,
        "value": value,
        "default": spec.default,
        "source": source,
        "secret": spec.secret,
        "high_risk": spec.high_risk,
        "applies": spec.applies,
        "description": spec.description,
        # is_set：非空且不等于默认空串，标识密钥是否已配置。
        "is_set": bool(value) and value != "",
    }


def effective_config() -> list[dict[str, Any]]:
    """构造 GET /api/config 的分组结构（secret 字段也返回真实值 + is_set）。"""
    groups: list[dict[str, Any]] = []
    for group_key, group_label in GROUPS:
        fields = [
            _field_dict(spec) for spec in FIELD_SPECS if spec.group == group_key
        ]
        groups.append({"key": group_key, "label": group_label, "fields": fields})
    return groups


def apply_overlay_to_env(overlay: dict[str, str]) -> None:
    """把覆盖层中存在的键 set 进 os.environ（不主动 unset 其它键）。"""
    for key, value in overlay.items():
        os.environ[key] = value
        _applied_keys.add(key)


def update_overlay(changes: dict[str, str | None]) -> None:
    """合并 changes 到覆盖层并落盘 + 重新应用到 os.environ。

    ``None`` 代表从覆盖层删除该键（回落 env/默认）；被删除且我们曾写过的键，
    从 os.environ 中 pop 掉。
    """
    overlay = load_overlay()
    removed: list[str] = []
    for key, value in changes.items():
        if value is None:
            overlay.pop(key, None)
            removed.append(key)
        else:
            overlay[key] = value
    save_overlay(overlay)
    # 对被删除且我们写过的键执行 pop，避免残留旧 env 值。
    for key in removed:
        if key in _applied_keys:
            os.environ.pop(key, None)
            _applied_keys.discard(key)
    apply_overlay_to_env(overlay)


def reset_overlay() -> None:
    """清空覆盖层文件为 {} 并 pop 我们曾写过的键，使配置回落 env/默认。"""
    save_overlay({})
    for key in list(_applied_keys):
        os.environ.pop(key, None)
    _applied_keys.clear()

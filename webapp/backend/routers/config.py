"""GET/PUT/POST(reset) /api/config — 可视化系统配置读写 + 热生效。

读取 :mod:`config_store` 计算有效配置（overlay>env>default）；写入时校验脏字段、
合并落盘 + 写 ``os.environ`` + ``reset_engine()``，下一次请求现读到新值。
影响向量维度/存储位置的 ``rebuild`` 类改动返回 ``warnings`` 指引用户重建索引。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config_schema import FIELDS_BY_KEY
from ..config_store import (
    SECRET_MASK,
    effective_config,
    reset_overlay,
    update_overlay,
)
from ..engine_provider import reset_engine

router = APIRouter(prefix="/api", tags=["config"])


class ConfigUpdate(BaseModel):
    values: dict[str, str | None]


def _validate(values: dict[str, str | None]) -> list[dict[str, str]]:
    """校验脏字段，返回错误列表（空=全通过）。"""
    errors: list[dict[str, str]] = []
    for key, value in values.items():
        spec = FIELDS_BY_KEY.get(key)
        if spec is None:
            errors.append({"key": key, "error": "未知配置项"})
            continue
        if value is None or value == "":
            # None=删除该键；空串=清空/回落，均放过。
            continue
        if spec.type == "int":
            try:
                parsed = int(value)
            except ValueError:
                errors.append({"key": key, "error": "必须是正整数"})
                continue
            if parsed <= 0:
                errors.append({"key": key, "error": "必须是正整数"})
        elif spec.type == "url":
            if not (value.startswith("http://") or value.startswith("https://")):
                errors.append(
                    {"key": key, "error": "必须以 http:// 或 https:// 开头"}
                )
    return errors


def _strip_masked_secrets(
    values: dict[str, str | None],
) -> dict[str, str | None]:
    """忽略等于掩码占位串的 secret 值（视为未改，不写覆盖层）。"""
    cleaned: dict[str, str | None] = {}
    for key, value in values.items():
        spec = FIELDS_BY_KEY.get(key)
        if spec is not None and spec.secret and value == SECRET_MASK:
            continue
        cleaned[key] = value
    return cleaned


def _rebuild_warnings(changes: dict[str, str | None]) -> list[str]:
    rebuild_keys = [
        key
        for key in changes
        if (spec := FIELDS_BY_KEY.get(key)) is not None and spec.applies == "rebuild"
    ]
    if not rebuild_keys:
        return []
    keys_text = ", ".join(rebuild_keys)
    return [
        f"已修改影响向量维度/存储位置的项（{keys_text}），"
        "现有索引可能不兼容，请到上传页重建索引"
    ]


@router.get("/config")
def get_config() -> dict[str, Any]:
    return {"groups": effective_config()}


@router.put("/config")
def put_config(body: ConfigUpdate) -> dict[str, Any]:
    errors = _validate(body.values)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    changes = _strip_masked_secrets(body.values)
    update_overlay(changes)
    reset_engine()

    warnings = _rebuild_warnings(changes)
    # ``config`` 镜像 GET 的 ``{groups: [...]}`` 形状，保持前后端契约一致。
    return {"config": {"groups": effective_config()}, "warnings": warnings}


@router.post("/config/reset")
def post_config_reset() -> dict[str, Any]:
    reset_overlay()
    reset_engine()
    return {"config": {"groups": effective_config()}}

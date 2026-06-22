"""embedder spec 解析 + 短名注册表。

`resolve_embedder(spec)` 统一解析 CLI `--embedder` 与 webapp `MDGRAPH_EMBEDDER`：

- 按第一个 ":" 把 spec 切成 (key, arg)（arg 可为 "" / 缺省）。
- key 命中注册短名 → 调对应工厂，把可选 arg 传进去（`fastembed` / `openai`）。
- 否则把整串 spec 当 dotted import path（`module:attr` 或 `module.attr`）无参构造，
  向后兼容既有默认 `mdgraph.providers.fastembed_embedder:FastEmbedProvider`。
- 解析失败 / 路径不可导入 / attr 不存在 / 短名工厂出错 → ValueError（消息带 spec 原文）。

注：模型名如 `BAAI/bge-m3` 含 "/" 但不含 ":"，按第一个 ":" 切分天然安全；裸模型名
必须带短名前缀（`fastembed:BAAI/bge-m3`），否则会落到 dotted-path 分支而不可导入。
"""

from __future__ import annotations

import importlib
from typing import Callable, Optional, Tuple

from mdgraph.providers.base import EmbeddingProvider


def _make_fastembed(arg: Optional[str]) -> EmbeddingProvider:
    from mdgraph.providers.fastembed_embedder import FastEmbedProvider

    return FastEmbedProvider(model_name=arg or "BAAI/bge-small-zh-v1.5")


def _make_openai(arg: Optional[str]) -> EmbeddingProvider:
    from mdgraph.providers.openai_embedder import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(model=arg or None)


# 名 → 工厂（arg: str | None）。模块级公开、可扩展（后续加 voyage 等只需注册一项）。
EMBEDDER_REGISTRY: dict[str, Callable[[Optional[str]], EmbeddingProvider]] = {
    "fastembed": _make_fastembed,
    "openai": _make_openai,
}


def _parse_spec(spec: str) -> Tuple[str, Optional[str]]:
    """按第一个 ":" 把 spec 切成 (key, arg)；无 ":" 则 arg 为 None。不构造任何 provider。"""
    if ":" in spec:
        key, _, arg = spec.partition(":")
        return key, arg
    return spec, None


def _load_dotted(path: str) -> object:
    """加载 `module:attr` 或 `module.attr` 指向的对象并返回（不构造）。"""
    if ":" in path:
        module_name, attr = path.split(":", 1)
    else:
        module_name, attr = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def resolve_embedder(spec: str) -> EmbeddingProvider:
    """把 spec 解析成 EmbeddingProvider 实例。

    短名命中注册表则走工厂；否则当 dotted-path 无参构造（向后兼容）。
    任何失败抛 ValueError（带 spec 原文）。
    """
    key, arg = _parse_spec(spec)
    factory = EMBEDDER_REGISTRY.get(key)
    if factory is not None:
        try:
            return factory(arg)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"构造 embedder spec {spec!r} 失败: {exc}") from exc
    # dotted-path 分支（向后兼容）
    try:
        obj = _load_dotted(spec)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ValueError(f"无法加载 embedder spec {spec!r}: {exc}") from exc
    try:
        return obj()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"构造 embedder spec {spec!r} 失败: {exc}") from exc

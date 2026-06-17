"""批量 embedding：按 provider 批上限分批调用，拼接结果。"""

from __future__ import annotations

from mdgraph.providers.base import EmbeddingProvider


def embed_texts(
    embedder: EmbeddingProvider, texts: list[str], batch_size: int = 64
) -> list[list[float]]:
    """对 texts 分批调用 embedder.embed，返回与输入等长、顺序一致的向量列表。"""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(embedder.embed(texts[i : i + batch_size]))
    return out

"""真实 embedding provider：本地 fastembed（无需 API key）。"""

from __future__ import annotations

from mdgraph.providers.base import EmbeddingProvider


class FastEmbedProvider(EmbeddingProvider):
    """用 fastembed 本地模型批量生成向量。

    选用无需 query/passage 前缀的模型（默认中文 bge-small-zh-v1.5），
    因 EmbeddingProvider.embed() 不区分 query/passage。dim 由探针嵌入测得，
    不依赖 fastembed 内部元数据结构。model 参数仅供测试注入。
    """

    def __init__(
        self, model_name: str = "BAAI/bge-small-zh-v1.5", model=None
    ) -> None:
        if model is None:
            from fastembed import TextEmbedding

            model = TextEmbedding(model_name=model_name)
        self._model = model
        self._raw_name = model_name
        self._dim = len(self.embed(["x"])[0])

    @property
    def name(self) -> str:
        return self._raw_name.replace("/", "_")

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._model.embed(list(texts))]

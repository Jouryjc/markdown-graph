"""OpenAI/Ollama 兼容 embedding provider：openai SDK → OpenAI 兼容端点（默认本地 Ollama）。

镜像 LocalLLMExtractor 的「openai SDK + 本地优先默认 + env 覆盖 + client 注入」模式：

- lazy import：仅当未注入 client 时才 `from openai import OpenAI`，离线测试不触发、不联网。
- env 覆盖：MDGRAPH_EMBED_MODEL / MDGRAPH_EMBED_BASE_URL / MDGRAPH_EMBED_API_KEY。
- 本地优先默认：base_url=http://localhost:11434/v1、api_key=ollama、model=nomic-embed-text，
  开箱即对接本地 Ollama；指向云端 OpenAI 时设三件套
  (https://api.openai.com/v1 + 真实 key + 如 text-embedding-3-small)。
- dim：构造时 `len(self.embed(["x"])[0])` 探一次（同 FastEmbedProvider）。
- name：清洗后的模型 id，令向量库表按模型版本化（换模型 ⇒ 必须重建 store）。
"""

from __future__ import annotations

import os

from mdgraph.providers.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        batch_size: int = 128,
        client=None,
    ) -> None:
        if client is None:
            from openai import OpenAI

            base_url = (
                base_url
                or os.environ.get("MDGRAPH_EMBED_BASE_URL")
                or "http://localhost:11434/v1"
            )
            api_key = api_key or os.environ.get("MDGRAPH_EMBED_API_KEY") or "ollama"
            client = OpenAI(base_url=base_url, api_key=api_key)
        self._client = client
        self._model = model or os.environ.get("MDGRAPH_EMBED_MODEL") or "nomic-embed-text"
        self._batch = batch_size
        self._dim = len(self.embed(["x"])[0])

    @property
    def name(self) -> str:
        return self._model.replace("/", "_").replace(":", "_")

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            out.extend([float(x) for x in d.embedding] for d in resp.data)
        return out

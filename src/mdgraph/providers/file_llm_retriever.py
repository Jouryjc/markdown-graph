"""LLM 文件检索 provider：在持久化的真实 .md 文件上用 prompt 选相关段落。

镜像 ``local_llm_extractor.py`` 范式：真实 openai SDK 仅在 ``client is None`` 时懒导入、
``client=`` 可注入（测试用假 client）、复用 ``MDGRAPH_LLM_*`` 默认、失败降级空（不抛崩查询）。
不做 TF/BM25 等排序——LLM 给出的先后顺序即排序。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from mdgraph.retrieve import Context

def _system_prompt(k: int) -> str:
    """system 提示：检索助手，只返回顶层 JSON 数组、段落逐字出自文档、最多 k 条。

    用普通拼接（非 str.format）以免提示里的 JSON 花括号被当作格式占位符。
    """
    return (
        "你是一个文档检索助手。给定用户的查询（query）与若干文档（每个含 path 与内容），"
        "请找出与查询最相关的段落。段落必须**逐字出自**给定文档内容，不要臆造或改写。"
        "严格只输出一个 JSON 数组，不要任何额外文字或 markdown 围栏，元素形如 "
        '[{"path":"<文档 path>","snippet":"<相关段落原文>"}]，按相关性从高到低排序，'
        "最多 " + str(k) + " 条。若没有相关内容，输出空数组 []。"
    )


def _extract_json_array(text: str) -> list | None:
    """从可能含 markdown 围栏/前后解释文字的输出里鲁棒提取顶层 JSON 数组。

    思路改写自 ``local_llm_extractor._extract_json``（那里提取的是 dict 对象），
    本处文件检索返回的是顶层 JSON 数组，故剥 markdown 代码围栏后 ``json.loads``，
    结果非 list 则返回 None。
    """
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = (fence.group(1) if fence else text).strip()
    for attempt in (candidate, _first_balanced_array(candidate)):
        if not attempt:
            continue
        try:
            obj = json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, list):
            return obj
    return None


def _first_balanced_array(s: str) -> str | None:
    """返回 s 中第一个括号平衡的 [...] 子串；无则 None。

    思路来自 ``local_llm_extractor._first_balanced_object``（那里平衡的是 ``{}``），
    本处平衡的是顶层数组的 ``[]``。
    """
    start = s.find("[")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


class FileLLMRetriever:
    def __init__(
        self,
        model=None,
        base_url=None,
        api_key=None,
        client=None,
        max_chars_per_batch: int = 12000,
    ) -> None:
        if client is None:
            from openai import OpenAI

            base_url = base_url or os.environ.get("MDGRAPH_LLM_BASE_URL") or "http://localhost:11434/v1"
            api_key = api_key or os.environ.get("MDGRAPH_LLM_API_KEY") or "ollama"
            client = OpenAI(base_url=base_url, api_key=api_key)
        self._client = client
        self._model = model or os.environ.get("MDGRAPH_LLM_MODEL") or "qwen2.5:3b"
        self._budget = max_chars_per_batch

    def retrieve(self, query: str, source_dir: Path, k: int = 8) -> list[Context]:
        source_dir = Path(source_dir)
        docs = self._read_docs(source_dir)
        if not docs:
            return []
        known_paths = {path for path, _ in docs}
        # 按 max_chars_per_batch 把 (path, 内容) 分批，每批一次 LLM 调用。
        hits: list[tuple[str, str]] = []
        for batch in self._batches(docs):
            hits.extend(self._query_batch(query, batch, known_paths, k))
        # 合并各批，按 LLM 给出的先后顺序裁剪到 k（不做 TF/BM25 排序）。
        hits = hits[:k]
        # 映射为引擎层 Context。注意 from_graph 是 webapp schema 层字段（标注图扩展命中），
        # 引擎 Context 无此字段；文件检索本就不经图扩展，由 webapp 路由按 mode 置 False。
        return [
            Context(
                chunk_id=f"file::{path}::{i}",
                text=snippet,
                score=(k - i) / k,
                doc_id="",
                source_path=path,
                heading_path="",
            )
            for i, (path, snippet) in enumerate(hits)
        ]

    def _read_docs(self, source_dir: Path) -> list[tuple[str, str]]:
        """读 source_dir 下全部 .md，返回 (相对 source_dir 的 posix path, 内容)。"""
        out: list[tuple[str, str]] = []
        if not source_dir.is_dir():
            return out
        for f in sorted(source_dir.rglob("*.md")):
            try:
                rel = f.relative_to(source_dir).as_posix()
            except ValueError:
                rel = f.name
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 - 读不了的文件跳过，不影响其余
                continue
            out.append((rel, content))
        return out

    def _batches(self, docs: list[tuple[str, str]]):
        """按字符预算把 (path, 内容) 分批；单文档超预算也独占一批（不切分）。"""
        batch: list[tuple[str, str]] = []
        size = 0
        for path, content in docs:
            cost = len(path) + len(content)
            if batch and size + cost > self._budget:
                yield batch
                batch, size = [], 0
            batch.append((path, content))
            size += cost
        if batch:
            yield batch

    def _query_batch(
        self,
        query: str,
        batch: list[tuple[str, str]],
        known_paths: set[str],
        k: int,
    ) -> list[tuple[str, str]]:
        """一批文档一次 LLM 调用，返回 [(path, snippet)]；本批任何异常 → 跳过该批不抛。"""
        docs_blob = "\n\n".join(
            f"### path: {path}\n{content}" for path, content in batch
        )
        user = f"query: {query}\n\n文档：\n{docs_blob}"
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                messages=[
                    {"role": "system", "content": _system_prompt(k)},
                    {"role": "user", "content": user},
                ],
            )
            content = resp.choices[0].message.content or ""
        except Exception:  # noqa: BLE001 - LLM/网络失败降级：跳过该批
            return []
        items = _extract_json_array(content)
        if items is None:
            return []
        out: list[tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            snippet = item.get("snippet")
            # 逐条防御：path/snippet 须为非空字符串，且 path 属于已知文件集才取（拒臆造路径）。
            if not isinstance(path, str) or not path.strip():
                continue
            if not isinstance(snippet, str) or not snippet.strip():
                continue
            if path not in known_paths:
                continue
            out.append((path, snippet))
        return out

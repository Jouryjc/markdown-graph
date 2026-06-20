"""真实 provider 端到端 demo：构建 examples/ai_kb 图谱并量化对比检索效果。

运行（需先在项目根 .env 填好凭证，并 `pip install fastembed`）：
    PYTHONPATH=src python examples/run_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mdgraph.engine import MarkdownGraph
from mdgraph.models import EdgeType
from mdgraph.retrieve import Retriever

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "examples" / "ai_kb"
STORE = ROOT / "examples" / ".demo_store"


def load_env(path: Path) -> dict:
    """解析 .env（KEY=VALUE，忽略空行与 # 注释），写入 os.environ 并返回 dict。"""
    env: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key:
            env[key] = val
            os.environ.setdefault(key, val)
    return env


def compare_retrieval(vector_store, embedder, graph_store, queries, k: int = 5) -> list[dict]:
    out = []
    for q in queries:
        vonly = Retriever(vector_store, embedder).retrieve(q, k=k)
        dual = Retriever(vector_store, embedder, graph_store=graph_store).retrieve(q, k=k)
        v_ids = [c.chunk_id for c in vonly.contexts]
        d_ids = [c.chunk_id for c in dual.contexts]
        out.append(
            {
                "query": q,
                "vector_only": v_ids,
                "dual": d_ids,
                "graph_added": [c for c in d_ids if c not in v_ids],
            }
        )
    return out


def top_mentioned_entities(graph_store, top: int = 10) -> list[tuple[str, int]]:
    g = graph_store.to_networkx()
    counts = []
    for n, data in g.nodes(data=True):
        if data.get("type") == "entity":
            mentions = sum(
                1 for _, _, k in g.in_edges(n, keys=True) if k == EdgeType.MENTIONS.value
            )
            name = data.get("meta", {}).get("name", n)
            counts.append((name, mentions))
    counts.sort(key=lambda x: (-x[1], x[0]))
    return counts[:top]


def main() -> int:
    load_env(ROOT / ".env")
    if not (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        print("缺少凭证：请在项目根 .env 填写 ANTHROPIC_AUTH_TOKEN(+ANTHROPIC_BASE_URL) 或 ANTHROPIC_API_KEY", file=sys.stderr)
        return 1
    try:
        from mdgraph.providers.fastembed_embedder import FastEmbedProvider
        from mdgraph.providers.anthropic_extractor import ClaudeExtractor
    except ImportError as exc:
        print(f"缺少依赖：{exc}（请 `pip install fastembed`）", file=sys.stderr)
        return 1

    print("== 构建图谱（首次会下载 embedding 模型 + 调用 Claude 抽取，请稍候）==")
    try:
        embedder = FastEmbedProvider()
    except Exception as exc:  # noqa: BLE001
        print(f"embedding 模型加载失败（需联网下载一次）：{exc}", file=sys.stderr)
        return 1
    mg = None
    try:
        mg = MarkdownGraph(STORE, embedder=embedder, llm=ClaudeExtractor())
        report = mg.build([CORPUS], incremental=False)
        print(
            f"indexed={report.indexed} entities={report.entities} "
            f"errors={len(report.errors)} warnings={len(report.warnings)}"
        )
        print("stats:", mg.stats())

        queries = [
            "如何提升 RAG 的召回质量",
            "Agent 怎么调用工具",
            "向量数据库和近似最近邻",
            "用知识图谱做图加向量双引擎检索",
        ]
        print("\n== 纯向量 vs 图+向量双引擎 ==")
        for row in compare_retrieval(mg.vector_store, embedder, mg.graph_store, queries):
            print(f"\n[查询] {row['query']}")
            print(f"  纯向量 top: {row['vector_only']}")
            print(f"  双引擎 top: {row['dual']}")
            print(f"  ← 图扩展新增（纯向量漏掉）: {row['graph_added']}")

        print("\n== 子图（首个查询命中结果的诱解释结构）==")
        first = Retriever(mg.vector_store, embedder, graph_store=mg.graph_store).retrieve(queries[0], k=5)
        sg = first.subgraph
        print(f"  子图节点 {len(sg['nodes'])} 个、边 {len(sg['edges'])} 条")

        print("\n== 跨文档实体合并（被最多 chunk MENTIONS 的实体）==")
        for name, cnt in top_mentioned_entities(mg.graph_store, top=10):
            print(f"  {name}: {cnt}")
    finally:
        if mg is not None:
            mg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

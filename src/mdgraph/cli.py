"""mdgraph 命令行：index / query / stats / graph export。

provider 无关：embedder/llm 经 dotted-path `pkg.mod:attr` 动态加载，CLI 不绑定
任何具体 provider 实现。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Optional

import typer

from mdgraph.engine import MarkdownGraph
from mdgraph.providers.registry import resolve_embedder

app = typer.Typer(add_completion=False, help="markdown 图谱 + 向量双引擎检索引擎")

_EMBEDDER_HELP = (
    "embedder spec：短名 fastembed:<model> / openai:<model>，或 dotted-path pkg.mod:attr"
)


def _load(dotted: str):
    """加载 dotted-path `pkg.mod:attr` 指向的 provider 并无参构造（仍用于 --llm）。"""
    if ":" not in dotted:
        raise typer.BadParameter(f"provider 须为 'pkg.mod:attr' 形式：{dotted}")
    mod_path, _, attr = dotted.partition(":")
    try:
        obj = getattr(importlib.import_module(mod_path), attr)
    except (ImportError, AttributeError) as exc:
        raise typer.BadParameter(f"无法加载 provider {dotted}: {exc}")
    try:
        return obj()
    except Exception as exc:  # noqa: BLE001
        raise typer.BadParameter(f"构造 provider {dotted} 失败: {exc}")


def _load_embedder(spec: str):
    """经注册表解析 --embedder spec；失败包成 typer.BadParameter 保持现有错误呈现。"""
    try:
        return resolve_embedder(spec)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))


@app.command()
def index(
    paths: List[Path] = typer.Argument(..., help="markdown 文件或目录"),
    store: Path = typer.Option(Path(".mdgraph"), "--store", help="存储目录"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help=_EMBEDDER_HELP),
    llm: Optional[str] = typer.Option(None, "--llm", help="pkg.mod:attr"),
    full: bool = typer.Option(False, "--full", help="全量重建（不增量）"),
    max_chars: int = typer.Option(1200, "--max-chars"),
    overlap: int = typer.Option(150, "--overlap"),
) -> None:
    emb = _load_embedder(embedder) if embedder else None
    llm_obj = _load(llm) if llm else None
    mg = MarkdownGraph(store, embedder=emb, llm=llm_obj)
    try:
        report = mg.build(
            paths, incremental=not full, max_chars=max_chars, overlap=overlap
        )
        typer.echo(
            f"indexed={report.indexed} unchanged={report.unchanged} "
            f"removed={report.removed} reclaimed={report.reclaimed} "
            f"entities={report.entities} errors={len(report.errors)}"
        )
        for path, err in report.errors:
            typer.echo(f"  error: {path}: {err}", err=True)
    finally:
        mg.close()


@app.command()
def query(
    text: str = typer.Argument(..., help="查询文本"),
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help=_EMBEDDER_HELP),
    k: int = typer.Option(8, "-k", "--k", help="返回条数"),
    json_out: bool = typer.Option(False, "--json", help="输出完整 JSON"),
) -> None:
    if not embedder:
        typer.echo(
            "query 需要 --embedder 配置 embedding provider（短名或 dotted-path）", err=True
        )
        raise typer.Exit(code=1)
    emb = _load_embedder(embedder)
    mg = MarkdownGraph(store, embedder=emb)
    try:
        res = mg.retrieve(text, k=k)
        if json_out:
            typer.echo(res.model_dump_json(indent=2))
        else:
            for c in res.contexts:
                typer.echo(f"[{c.score:.4f}] {c.source_path} :: {c.heading_path}")
                typer.echo(f"    {c.text[:200].replace(chr(10), ' ')}")
    finally:
        mg.close()


@app.command()
def stats(
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help=_EMBEDDER_HELP),
) -> None:
    emb = _load_embedder(embedder) if embedder else None
    mg = MarkdownGraph(store, embedder=emb)
    try:
        for key, value in mg.stats().items():
            typer.echo(f"{key}: {value}")
    finally:
        mg.close()


graph_app = typer.Typer(help="图谱导出 / 检查")
app.add_typer(graph_app, name="graph")


@graph_app.command("export")
def graph_export(
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    seeds: Optional[str] = typer.Option(None, "--seeds", help="逗号分隔的种子节点 id"),
    hops: int = typer.Option(2, "--hops"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="写入文件"),
) -> None:
    import json as _json

    mg = MarkdownGraph(store)
    try:
        gs = mg.graph_store
        if seeds:
            seed_ids = [s.strip() for s in seeds.split(",") if s.strip()]
            dist = gs.expand(seed_ids, hops=hops)
            data = gs.subgraph(seed_ids + list(dist))
        else:
            data = gs.export_graph()
        text = _json.dumps(data, ensure_ascii=False, indent=2)
        if output:
            output.write_text(text, encoding="utf-8")
            typer.echo(
                f"wrote {len(data['nodes'])} nodes, {len(data['edges'])} edges to {output}"
            )
        else:
            typer.echo(text)
    finally:
        mg.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()

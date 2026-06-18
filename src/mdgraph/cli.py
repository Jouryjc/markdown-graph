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

app = typer.Typer(add_completion=False, help="markdown 图谱 + 向量双引擎检索引擎")


def _load(dotted: str):
    """加载 dotted-path `pkg.mod:attr` 指向的 provider 并无参构造。"""
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


@app.command()
def index(
    paths: List[Path] = typer.Argument(..., help="markdown 文件或目录"),
    store: Path = typer.Option(Path(".mdgraph"), "--store", help="存储目录"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help="pkg.mod:attr"),
    llm: Optional[str] = typer.Option(None, "--llm", help="pkg.mod:attr"),
    full: bool = typer.Option(False, "--full", help="全量重建（不增量）"),
    max_chars: int = typer.Option(1200, "--max-chars"),
    overlap: int = typer.Option(150, "--overlap"),
) -> None:
    emb = _load(embedder) if embedder else None
    llm_obj = _load(llm) if llm else None
    mg = MarkdownGraph(store, embedder=emb, llm=llm_obj)
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
    mg.close()


@app.command()
def query(
    text: str = typer.Argument(..., help="查询文本"),
    store: Path = typer.Option(Path(".mdgraph"), "--store"),
    embedder: Optional[str] = typer.Option(None, "--embedder", help="pkg.mod:attr"),
    k: int = typer.Option(8, "-k", "--k", help="返回条数"),
    json_out: bool = typer.Option(False, "--json", help="输出完整 JSON"),
) -> None:
    if not embedder:
        typer.echo(
            "query 需要 --embedder pkg.mod:attr 配置 embedding provider", err=True
        )
        raise typer.Exit(code=1)
    emb = _load(embedder)
    mg = MarkdownGraph(store, embedder=emb)
    res = mg.retrieve(text, k=k)
    if json_out:
        typer.echo(res.model_dump_json(indent=2))
    else:
        for c in res.contexts:
            typer.echo(f"[{c.score:.4f}] {c.source_path} :: {c.heading_path}")
            typer.echo(f"    {c.text[:200].replace(chr(10), ' ')}")
    mg.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()

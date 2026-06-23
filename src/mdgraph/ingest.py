"""发现与读取 markdown 文件。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def discover(
    paths: list[str | Path],
    exclude: list[str | Path] | None = None,
) -> list[Path]:
    """递归收集 .md 文件，按路径排序、去重（按 resolve 后的真实路径）。

    exclude：可选的目录列表，落在其中（含子目录）的 .md 会被跳过。用于把引擎
    持久化的源副本目录（store_dir/source）排除在索引/再持久化之外——否则当 store
    目录嵌在被索引的根目录内时，源副本会被反复 discover 进而污染索引。
    """
    excluded = [Path(e).resolve() for e in (exclude or [])]

    def _is_excluded(rp: Path) -> bool:
        return any(rp == ex or ex in rp.parents for ex in excluded)

    out: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.md")):
                rp = f.resolve()
                if rp not in seen and not _is_excluded(rp):
                    seen.add(rp)
                    out.append(f)
        elif p.is_file() and p.suffix == ".md":
            rp = p.resolve()
            if rp not in seen and not _is_excluded(rp):
                seen.add(rp)
                out.append(p)
    return out


def read_file(path: str | Path) -> tuple[str, str, float]:
    """返回 (text, sha256_hex, mtime)。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    mtime = path.stat().st_mtime
    return text, h, mtime

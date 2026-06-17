"""发现与读取 markdown 文件。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def discover(paths: list[str | Path]) -> list[Path]:
    """递归收集 .md 文件，按路径排序、去重（按 resolve 后的真实路径）。"""
    out: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.md")):
                rp = f.resolve()
                if rp not in seen:
                    seen.add(rp)
                    out.append(f)
        elif p.is_file() and p.suffix == ".md":
            rp = p.resolve()
            if rp not in seen:
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

"""确定性 ID 生成：全部由 hex / 下划线 / 数字组成，无引号。"""

from __future__ import annotations

import hashlib


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def doc_id(relpath: str) -> str:
    return "d_" + _h(relpath)


def section_id(doc_id: str, sec_idx: int) -> str:
    return f"{doc_id}_s{sec_idx}"


def chunk_id(doc_id: str, sec_idx: int, chunk_idx: int) -> str:
    return f"{doc_id}_s{sec_idx}_c{chunk_idx}"


def tag_id(name: str) -> str:
    return "t_" + _h(name.lower())

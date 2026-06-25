"""确定性 ID 生成：全部由 hex / 下划线 / 数字组成，无引号。"""

from __future__ import annotations

import hashlib
import re


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def doc_id(relpath: str) -> str:
    return "d_" + _h(relpath)


def section_id(doc_id: str, sec_idx: int) -> str:
    return f"{doc_id}_s{sec_idx}"


def chunk_id(doc_id: str, sec_idx: int, chunk_idx: int) -> str:
    return f"{doc_id}_s{sec_idx}_c{chunk_idx}"


def doc_id_from_chunk(chunk_id: str) -> str:
    """从 chunk_id / section_id 反推出所属 doc_id（`d_<hash>` 前两段）。

    chunk_id 形如 ``d_<hash>_s<sec>_c<chunk>``、section_id 形如 ``d_<hash>_s<sec>``，
    doc_id 恒为前两个下划线分隔段 ``d_<hash>``。无法识别时返回空串。
    """
    parts = chunk_id.split("_")
    if len(parts) >= 2 and parts[0] == "d":
        return f"{parts[0]}_{parts[1]}"
    return ""


def tag_id(name: str) -> str:
    return "t_" + _h(name.lower())


_NORM_RE = re.compile(r"\W+")


def normalize_name(name: str) -> str:
    """小写 + 把非单词字符（标点/空白，Unicode 友好）连续段折成单个空格 + 首尾 strip。"""
    return _NORM_RE.sub(" ", name.lower()).strip()


def entity_id(name: str) -> str:
    return "e_" + _h(normalize_name(name))


def sag_event_id(chunk_id: str) -> str:
    return "ev_" + _h(chunk_id)

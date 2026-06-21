"""Safe archive extraction for the upload flow.

Pure-stdlib (zipfile, tarfile, os, pathlib) so it is unit-testable with crafted
archives and NO network. This is the highest-risk surface; the extractor defends
against ZIP-SLIP / path traversal, tar symlink/hardlink/special members, and
decompression bombs, and only writes markdown files (.md / .markdown) into a
caller-provided fresh temp dir.

Public API
----------
``ExtractLimits``  — value object holding the four bomb-limits.
``ArchiveError``   — raised (ValueError subclass) on ANY violation or corruption.
``extract_markdown_archive(archive_path, dest, *, limits) -> int``
    Extracts all markdown files from the archive into ``dest`` (preserving the
    in-archive directory layout), normalizing ``.markdown`` -> ``.md`` on write,
    and returns the number of markdown files written. Raises ArchiveError on any
    security violation or corrupt/invalid archive.
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Defaults mirror webapp.backend.settings; the runner passes settings-derived
# limits, these are only a self-contained fallback for direct/unit use.
_DEFAULT_MAX_ENTRIES = 5000
_DEFAULT_MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024
_DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024

_READ_CHUNK = 64 * 1024
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


class ArchiveError(ValueError):
    """Raised on any extraction violation or corrupt/invalid archive."""


@dataclass(frozen=True)
class ExtractLimits:
    """Decompression-bomb limits. ``max_archive_bytes`` is enforced at upload
    time (router/job streaming), not here, but is carried for convenience."""

    max_archive_bytes: int = 50 * 1024 * 1024
    max_entries: int = _DEFAULT_MAX_ENTRIES
    max_total_uncompressed: int = _DEFAULT_MAX_TOTAL_UNCOMPRESSED
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES


def _is_zip(archive_path: Path) -> bool:
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        return True
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        return False
    # Fall back to magic sniffing for ambiguous names.
    return zipfile.is_zipfile(archive_path)


def _safe_member_name(name: str) -> str:
    """Validate an in-archive path. Return a normalized POSIX-relative path or
    raise ArchiveError on traversal / absolute / drive-letter paths."""
    if not name:
        raise ArchiveError("archive contains an entry with an empty name")
    # Normalize separators; reject Windows drive / UNC and absolute paths.
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or os.path.isabs(name):
        raise ArchiveError(f"archive entry has an absolute path: {name!r}")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise ArchiveError(f"archive entry has a drive-letter path: {name!r}")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ArchiveError(f"archive entry escapes via '..': {name!r}")
    if not parts:
        # Pure directory entry (e.g. "a/").
        return ""
    return "/".join(parts)


def _resolved_within(dest_real: str, rel: str) -> str:
    """Resolve ``rel`` under ``dest`` and confirm it stays inside dest."""
    target = os.path.realpath(os.path.join(dest_real, rel))
    if target != dest_real and not target.startswith(dest_real + os.sep):
        raise ArchiveError(f"archive entry escapes destination: {rel!r}")
    return target


def _normalize_md_name(rel: str) -> str:
    """Normalize any-case ``.md`` / ``.markdown`` suffix to lowercase ``.md``.

    The engine discovers files by globbing ``*.md`` (case-sensitive on
    case-sensitive filesystems), so an uppercase ``FOO.MD`` or ``FOO.MARKDOWN``
    would be written but never indexed — counted yet invisible. Lowercasing the
    suffix keeps the written-file count and the index in sync across platforms.
    """
    suffix = Path(rel).suffix
    if suffix.lower() in _MARKDOWN_SUFFIXES:
        return rel[: -len(suffix)] + ".md"
    return rel


def _write_file(target: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(data)


def extract_markdown_archive(
    archive_path: Path,
    dest: Path,
    *,
    limits: ExtractLimits | None = None,
) -> int:
    """Extract markdown files from ``archive_path`` into ``dest``.

    Returns the number of markdown files written. Raises ArchiveError on any
    security violation or corrupt archive. ``dest`` must already exist and be a
    fresh empty directory owned by the caller.
    """
    limits = limits or ExtractLimits()
    archive_path = Path(archive_path)
    dest = Path(dest)
    dest_real = os.path.realpath(dest)

    if _is_zip(archive_path):
        return _extract_zip(archive_path, dest_real, limits)
    return _extract_tar(archive_path, dest_real, limits)


def _extract_zip(archive_path: Path, dest_real: str, limits: ExtractLimits) -> int:
    written = 0
    total = 0
    try:
        with zipfile.ZipFile(archive_path) as zf:
            infos = zf.infolist()
            if len(infos) > limits.max_entries:
                raise ArchiveError(
                    f"archive has too many entries "
                    f"({len(infos)} > {limits.max_entries})"
                )
            for info in infos:
                rel = _safe_member_name(info.filename)
                if rel == "" or info.is_dir():
                    continue
                if Path(rel).suffix.lower() not in _MARKDOWN_SUFFIXES:
                    continue
                # Declared size is a hint; cap real writes regardless.
                if info.file_size > limits.max_file_bytes:
                    raise ArchiveError(
                        f"archive member exceeds per-file limit: {info.filename!r}"
                    )
                out_rel = _normalize_md_name(rel)
                target = _resolved_within(dest_real, out_rel)
                data = _read_capped_zip(zf, info, limits.max_file_bytes)
                total += len(data)
                if total > limits.max_total_uncompressed:
                    raise ArchiveError(
                        "archive exceeds total uncompressed size limit"
                    )
                _write_file(target, data)
                written += 1
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"invalid or corrupt zip archive: {exc}") from exc
    return written


def _read_capped_zip(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int
) -> bytes:
    """Read at most cap+1 bytes; raise if the real stream exceeds cap."""
    with zf.open(info) as src:
        buf = bytearray()
        while True:
            chunk = src.read(_READ_CHUNK)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > cap:
                raise ArchiveError(
                    f"archive member exceeds per-file limit: {info.filename!r}"
                )
    return bytes(buf)


class _InflationGuard:
    """Wraps a *decompressed* byte stream and counts the bytes tarfile reads out
    of it, aborting once cumulative inflation exceeds the configured limit.

    The wrapped stream is the post-decompression tar byte stream (see
    :func:`_open_decompressed`), so every byte ``tarfile`` consumes to walk the
    archive — including the bodies of skipped (non-markdown) members that
    ``for member in tf`` must read past to reach the next header — is counted.
    This bounds the CPU/IO a tiny compressed upload can force, closing the
    decompression-bomb hole where only written markdown bytes were counted.
    """

    def __init__(self, fileobj, limit: int) -> None:
        self._fileobj = fileobj
        self._limit = limit
        self._consumed = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fileobj.read(size)
        self._consumed += len(chunk)
        if self._consumed > self._limit:
            raise ArchiveError("archive exceeds total uncompressed size limit")
        return chunk

    def close(self) -> None:
        try:
            self._fileobj.close()
        except Exception:
            pass


def _open_decompressed(archive_path: Path):
    """Open ``archive_path`` and return a sequential, decompressed byte stream of
    the underlying (uncompressed) tar, plus the streaming tar mode to use.

    Compression is sniffed from magic bytes so we can interpose our own
    decompressor and count the inflated bytes ourselves. Returns
    ``(fileobj, mode)`` where ``mode`` is always ``"r|"`` (uncompressed
    streaming) because ``fileobj`` is already decompressed.
    """
    raw = open(archive_path, "rb")
    try:
        magic = raw.read(6)
        raw.seek(0)
        if magic.startswith(b"\x1f\x8b"):
            import gzip

            return gzip.GzipFile(fileobj=raw), "r|"
        if magic.startswith(b"BZh"):
            import bz2

            return bz2.BZ2File(raw), "r|"
        if magic.startswith(b"\xfd7zXZ\x00"):
            import lzma

            return lzma.LZMAFile(raw), "r|"
        # Uncompressed tar (no inflation possible, but still streamed/counted).
        return raw, "r|"
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        raise


def _extract_tar(archive_path: Path, dest_real: str, limits: ExtractLimits) -> int:
    written = 0
    total = 0
    stream = None
    try:
        # Interpose our own decompressor and wrap the *decompressed* stream so
        # EVERY inflated byte tarfile reads is counted toward
        # max_total_uncompressed — including bodies of skipped non-markdown
        # members that the iterator must read past. Streaming ("r|") mode reads
        # members strictly in order, which matches our read-immediately loop and
        # never seeks (so a non-seekable decompressor wrapper is fine).
        stream, tar_mode = _open_decompressed(archive_path)
        guard = _InflationGuard(stream, limits.max_total_uncompressed)
        with tarfile.open(fileobj=guard, mode=tar_mode) as tf:
            count = 0
            for member in tf:
                count += 1
                if count > limits.max_entries:
                    raise ArchiveError(
                        f"archive has too many entries (> {limits.max_entries})"
                    )
                if member.isdir():
                    continue
                # Reject anything that is not a regular file: symlinks,
                # hardlinks, devices, FIFOs, etc.
                if not member.isreg():
                    raise ArchiveError(
                        f"archive member is not a regular file: {member.name!r}"
                    )
                rel = _safe_member_name(member.name)
                if rel == "":
                    continue
                if Path(rel).suffix.lower() not in _MARKDOWN_SUFFIXES:
                    continue
                if member.size > limits.max_file_bytes:
                    raise ArchiveError(
                        f"archive member exceeds per-file limit: {member.name!r}"
                    )
                out_rel = _normalize_md_name(rel)
                target = _resolved_within(dest_real, out_rel)
                data = _read_capped_tar(tf, member, limits.max_file_bytes)
                total += len(data)
                if total > limits.max_total_uncompressed:
                    raise ArchiveError(
                        "archive exceeds total uncompressed size limit"
                    )
                _write_file(target, data)
                written += 1
    except ArchiveError:
        # Our own violations (incl. the inflation-guard tripping inside tarfile)
        # propagate unchanged.
        raise
    except Exception as exc:  # noqa: BLE001 — normalize any failure to ArchiveError
        # tarfile (or our interposed decompressor) may wrap an ArchiveError
        # raised from the guard's read() while advancing the stream; surface the
        # original limit error. Any other failure here is a corrupt/invalid
        # archive (tarfile.TarError, gzip.BadGzipFile, lzma.LZMAError, OSError,
        # EOFError, ...) now that we decode the compressed stream ourselves, so
        # map it to ArchiveError to preserve the "ArchiveError on any corruption"
        # contract.
        if isinstance(exc.__cause__, ArchiveError):
            raise exc.__cause__
        if isinstance(exc.__context__, ArchiveError):
            raise exc.__context__
        raise ArchiveError(f"invalid or corrupt tar archive: {exc}") from exc
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
    return written


def _read_capped_tar(
    tf: tarfile.TarFile, member: tarfile.TarInfo, cap: int
) -> bytes:
    src = tf.extractfile(member)
    if src is None:
        raise ArchiveError(f"archive member has no readable content: {member.name!r}")
    buf = bytearray()
    with src:
        while True:
            chunk = src.read(_READ_CHUNK)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > cap:
                raise ArchiveError(
                    f"archive member exceeds per-file limit: {member.name!r}"
                )
    return bytes(buf)

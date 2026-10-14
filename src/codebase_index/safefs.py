"""Read repo files without ever leaving the repo: every repo-file read in this package goes through here.

A path is accepted only when every component below REPO_ROOT is a real directory and the last one a
regular file. Symlinks and Windows junctions are refused anywhere in the path, even when they point back
into the repo, because an in-repo link can alias a git-ignored secret (`visible.py -> .env`).

On POSIX the read is race-free: each directory is opened with O_NOFOLLOW relative to the already-checked
parent descriptor, and the file is type- and size-checked through the same descriptor it is read from.
Windows has no openat(), so the path is lstat-walked, opened, and the opened file's id compared with the
walked one; a swap between check and open is refused.
"""
from __future__ import annotations

import os
import stat as _stat

from . import config

# Windows reparse tags of a symlink and a junction (the stat constants exist only on Windows builds).
_LINK_TAGS = (getattr(_stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
              getattr(_stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003))
_OFLAGS = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_BINARY", 0)
_HAVE_AT = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd)


def _is_link(st: os.stat_result) -> bool:
    # Only real links: OneDrive / dedup reparse points are ordinary files and must stay readable.
    return _stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


def _parts(rel: str) -> list[str] | None:
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") or "\\" in p or ":" in p or "\0" in p for p in parts):
        return None
    return parts


def lstat_file(rel: str, dir_cache: dict | None = None) -> os.stat_result | None:
    """lstat() of a regular repo file, or None if it is missing, not regular, or any component is a link.

    dir_cache (one dict per scan) remembers directory verdicts so a full-repo scan stays one lstat per file."""
    parts = _parts(rel)
    if parts is None:
        return None
    path = str(config.REPO_ROOT)
    try:
        for part in parts[:-1]:
            path = os.path.join(path, part)
            ok = dir_cache.get(path) if dir_cache is not None else None
            if ok is None:
                st = os.lstat(path)
                ok = _stat.S_ISDIR(st.st_mode) and not _is_link(st)
                if dir_cache is not None:
                    dir_cache[path] = ok
            if not ok:
                return None
        st = os.lstat(os.path.join(path, parts[-1]))
    except (OSError, ValueError):
        return None
    return st if _stat.S_ISREG(st.st_mode) and not _is_link(st) else None


def _open_at(parts: list[str]) -> int:
    """POSIX: open the file component by component, refusing links at every level (raises OSError)."""
    fd = os.open(config.REPO_ROOT, os.O_RDONLY | os.O_DIRECTORY | _OFLAGS)
    try:
        for part in parts[:-1]:
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _OFLAGS, dir_fd=fd)
            os.close(fd)
            fd = nfd
        # O_NONBLOCK: opening a FIFO must not hang; it is rejected by the fstat check below.
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _OFLAGS, dir_fd=fd)
    finally:
        os.close(fd)


def read_bytes(rel: str, max_bytes: int | None = None) -> bytes | None:
    """Contents of a regular file inside the repo, or None (link, escape, not regular, missing, too big)."""
    parts = _parts(rel)
    if parts is None:
        return None
    try:
        if _HAVE_AT:
            expect = None
            fd = _open_at(parts)
        else:
            expect = lstat_file(rel)
            if expect is None:
                return None
            fd = os.open(os.path.join(config.REPO_ROOT, *parts), os.O_RDONLY | _OFLAGS)
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            if not _stat.S_ISREG(st.st_mode):
                return None
            if expect is not None and (st.st_dev, st.st_ino) != (expect.st_dev, expect.st_ino):
                return None  # the path changed between the check and the open
            if max_bytes is not None and st.st_size > max_bytes:
                return None
            data = f.read() if max_bytes is None else f.read(max_bytes + 1)
    except (OSError, ValueError):
        return None
    return None if max_bytes is not None and len(data) > max_bytes else data


def read_small(path: os.PathLike | str, limit: int = 1 << 16) -> str:
    """First `limit` bytes of a small metadata file (e.g. under .git) as text; never blocks on a FIFO.

    Raises OSError, like Path.read_text, when it is missing or not a regular file."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | _OFLAGS)
    with os.fdopen(fd, "rb") as f:
        if not _stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError(f"not a regular file: {path}")
        return f.read(limit).decode("utf-8", "replace")

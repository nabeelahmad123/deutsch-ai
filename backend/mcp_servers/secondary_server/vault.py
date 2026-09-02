"""A small Markdown notes vault -- the storage behind MCP server #2.

Deliberately independent of MCP server #1: no DB, no scheduler, no shared code
beyond ``backend.tracing``. Notes are files under ``NOTES_VAULT_DIR``; a note
"name" is a safe relative path (``.md`` optional) that cannot escape the vault.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VAULT_DIR = "./_vault"
PROGRESS_NOTE = "progress.md"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._ -]+$")


class VaultError(ValueError):
    """A bad note name / path."""


@dataclass(frozen=True)
class NoteInfo:
    name: str
    bytes: int
    modified: str


@dataclass(frozen=True)
class ProgressEntry:
    note: str
    bytes: int
    appended: str


def vault_dir() -> Path:
    """The vault root, created if missing. Always fully resolved so path maths
    (relative_to, parents) is symlink-safe -- matters on macOS /var -> /private/var."""
    path = Path(os.environ.get("NOTES_VAULT_DIR") or DEFAULT_VAULT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _resolve(name: str) -> Path:
    raw = name.strip()
    if not raw or raw.startswith("/") or "\\" in raw:
        raise VaultError(f"unsafe note name: {name!r}")
    # Validate the caller's segments before we add a suffix.
    segments = raw.split("/")
    if any(seg == "" or set(seg) == {"."} or not _SAFE_SEGMENT.match(seg) for seg in segments):
        raise VaultError(f"unsafe note name: {name!r}")

    rel = raw if raw.endswith(".md") else raw + ".md"
    root = vault_dir()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise VaultError(f"note escapes the vault: {name!r}")
    return target


def list_notes() -> list[NoteInfo]:
    root = vault_dir()
    notes = []
    for path in sorted(root.rglob("*.md")):
        stat = path.stat()
        notes.append(
            NoteInfo(
                name=str(path.relative_to(root)),
                bytes=stat.st_size,
                modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.UTC).isoformat(),
            )
        )
    return notes


def read_note(name: str) -> str:
    path = _resolve(name)
    if not path.exists():
        raise VaultError(f"no note {name!r}")
    return path.read_text(encoding="utf-8")


def write_note(name: str, content: str) -> NoteInfo:
    path = _resolve(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _info(path)


def append_note(name: str, content: str) -> NoteInfo:
    path = _resolve(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = (
        ""
        if not existing or existing.endswith("\n\n")
        else ("\n" if existing.endswith("\n") else "\n\n")
    )
    path.write_text(existing + sep + content.rstrip() + "\n", encoding="utf-8")
    return _info(path)


def log_progress(
    summary: str, *, heading: str | None = None, date: str | None = None
) -> ProgressEntry:
    """Append a dated section to progress.md -- the weekly-summary export
    (CLAUDE.md section 10). Returns the note info and the block that was added."""
    day = (date or dt.date.today().isoformat()).strip()
    title = heading.strip() if heading else "Progress"
    block = f"## {day} — {title}\n\n{summary.strip()}\n"
    info = append_note(PROGRESS_NOTE, block)
    return ProgressEntry(note=info.name, bytes=info.bytes, appended=block)


def _info(path: Path) -> NoteInfo:
    stat = path.stat()
    return NoteInfo(
        name=str(path.relative_to(vault_dir())),
        bytes=stat.st_size,
        modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.UTC).isoformat(),
    )

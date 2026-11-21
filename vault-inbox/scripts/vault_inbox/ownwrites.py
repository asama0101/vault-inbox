"""Materials this plugin rewrote; `watch` must not take them for user edits."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path


def _file(root: Path) -> Path:
    return root / ".vault-inbox" / "own_writes.json"


def record(root: Path, entries: dict[str, list[int]]) -> None:
    """entries: vault path -> [mtime_ns, size] before our write, then after it."""
    if not entries:
        return
    old = _load(root)
    for path, entry in entries.items():
        if path in old:  # written twice since the baseline: keep the first "before"
            entry[:2] = old[path][:2]
    merged = {**old, **entries}
    _file(root).write_text(json.dumps(merged), encoding="utf-8")


def _load(root: Path) -> dict:
    try:
        data = json.loads(_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def take(root: Path) -> dict[str, list[int]]:
    """Read the records and forget them."""
    data = _load(root)
    with contextlib.suppress(OSError):
        _file(root).unlink()
    return data

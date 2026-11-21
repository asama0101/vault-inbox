from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from . import ownwrites
from .indexmd import is_generated

WATCHED = ("inbox", "project", "shared")


def _baseline_path(root: Path) -> Path:
    return root / ".vault-inbox" / "watch_baseline.json"


def snapshot(root: Path) -> dict[str, list[int]]:
    snap: dict[str, list[int]] = {}
    for top in WATCHED:
        base = root / top
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            rel_parts = p.relative_to(root).parts
            if not p.is_file() or is_generated(p.name):
                continue
            if any(part.startswith(".") for part in rel_parts[:-1]):
                continue
            try:
                st = p.stat()
            except OSError:
                continue  # vanished between listing and stat
            snap["/".join(rel_parts)] = [st.st_mtime_ns, st.st_size]
    return snap


def save_baseline(root: Path) -> None:
    ownwrites.take(root)  # the snapshot already contains them
    _baseline_path(root).write_text(json.dumps(snapshot(root)), encoding="utf-8")


def absorb_own_writes(root: Path, doc_paths: set[str]) -> None:
    """At the end of a pass, take only the pass's own writes into the baseline.

    The baseline was saved at the pass start. A pass changes watched files only
    by moving inbox files to registered paths (place/resume) and by rewriting the
    frontmatter of Markdown materials (recorded in ownwrites). So a new path that
    is now a registered doc, the inbox file of the same name that left, and a
    recorded file that was unchanged since the baseline and still has the size and
    time we left it with are absorbed. Any other difference (a user edit, move,
    delete or new file made while a question was open) stays, so `changed`
    reports it.
    """
    base = _load_baseline(root)
    if base is None:
        save_baseline(root)
        return
    own = ownwrites.take(root)
    cur = snapshot(root)
    placed = [p for p in cur if p not in base and p in doc_paths]
    names = {p.rsplit("/", 1)[-1] for p in placed}
    for p in placed:
        base[p] = cur[p]
    for p in [p for p in base if p.startswith("inbox/") and p not in cur]:
        if p.split("/", 1)[1] in names:
            del base[p]
    for p, (*before, mtime, size) in own.items():
        # only when the user had not touched it since the baseline
        if base.get(p) == before and cur.get(p) == [mtime, size]:
            base[p] = cur[p]
    _baseline_path(root).write_text(json.dumps(base), encoding="utf-8")


def absorb_recorded(root: Path) -> None:
    """Take the recorded rewrites into the baseline now (a run outside a pass, such as
    the recording of a relation by `ask`). Without a baseline there is nothing to do."""
    own = ownwrites.take(root)
    base = _load_baseline(root)
    if base is None:
        return
    cur = snapshot(root)
    for p, (*before, mtime, size) in own.items():
        if base.get(p) == before and cur.get(p) == [mtime, size]:
            base[p] = cur[p]
    _baseline_path(root).write_text(json.dumps(base), encoding="utf-8")


def _load_baseline(root: Path) -> dict | None:
    try:
        return json.loads(_baseline_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def changed(root: Path) -> bool:
    """True if the current snapshot differs from the baseline.

    With no baseline there is nothing to compare against, so this is False.
    """
    base = _load_baseline(root)
    return base is not None and snapshot(root) != base


def poll(
    root: Path,
    interval: float,
    settle: float,
    once: bool = False,
    heartbeat: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Yield "CHANGED" once per settled change.

    A change is reported only after the snapshot has stayed unchanged for
    `settle` seconds. The baseline is never touched here; to avoid repeating
    the same change, the last reported snapshot is remembered.
    """
    reported = None
    while True:
        if heartbeat:
            heartbeat()
        base = _load_baseline(root)
        cur = snapshot(root)
        if base is None or cur == base:
            reported = None
        elif cur != reported:
            last, stable_since = cur, time.monotonic()
            while time.monotonic() - stable_since < settle:
                time.sleep(interval)
                if heartbeat:
                    heartbeat()
                now = snapshot(root)
                if now != last:
                    last, stable_since = now, time.monotonic()
            if _load_baseline(root) == last:  # organize saved the baseline meanwhile
                reported = None
                if once:
                    return
                continue
            reported = last
            yield "CHANGED"
            if once:
                return
            continue
        if once:
            return
        time.sleep(interval)

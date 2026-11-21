from __future__ import annotations

import shutil
from pathlib import Path

from .extract import ExtractError, extract_text, is_candidate
from .index import rebuild, save_text, text_dir
from .indexmd import is_generated
from .meta import Doc, MetaStore, file_hash, new_id
from .vault import DEPTH_LIMIT, vault_parts


class NameCollision(Exception):  # noqa: N818 - public name, used by the CLI and tests
    pass


class SourceMissing(Exception):  # noqa: N818 - public name, used by the CLI and tests
    pass


class BadName(Exception):  # noqa: N818 - public name, used by the CLI and tests
    pass


class PlaceFailed(Exception):  # noqa: N818 - public name, used by the CLI and tests
    """The original could not be moved to the destination (nothing was registered)."""


def clamp_dest(dest_rel: str) -> str:
    try:
        parts = vault_parts(dest_rel)
    except ValueError as e:
        raise ValueError(f"bad destination: {e}") from e
    return "/".join(parts[:DEPTH_LIMIT])


def existing_spelling(root: Path, dest_rel: str) -> str:
    """Use the spelling of a folder that already exists with different letter case.

    Foo and foo are one folder on Windows and macOS, so two spellings in meta.json
    would write two sets of notes into it. Only an unambiguous match is reused."""
    parts = []
    base = root
    for part in dest_rel.split("/"):
        try:
            names = [p.name for p in base.iterdir() if p.is_dir()]
        except OSError:
            names = []
        if part not in names:
            same = [n for n in names if n.casefold() == part.casefold()]
            if len(same) == 1:
                part = same[0]
        parts.append(part)
        base = base / part
    return "/".join(parts)


def _check_name(root: Path, name: str) -> None:
    """A plain file name directly in inbox/."""
    inbox = root / "inbox"
    if (
        not name
        or "/" in name
        or "\\" in name
        or ".." in name
        or name == "."
        or is_generated(name)
        or (inbox / name).resolve().parent != inbox.resolve()
    ):
        raise BadName(name)


def _item(
    name: str,
    status: str,
    reason: str = "",
    id: str = "",
    hash: str = "",
    text_path: str = "",
) -> dict:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "id": id,
        "hash": hash,
        "text_path": text_path,
    }


def remove_orphan_texts(root: Path, store: MetaStore) -> None:
    """Delete text files of ids that were never placed (left by earlier intakes)."""
    base = text_dir(root)
    if not base.is_dir():
        return
    for p in base.glob("*.txt"):
        if store.get(p.stem) is None:
            p.unlink(missing_ok=True)


def _inbox_key(p: Path) -> tuple[str, str]:
    """(name, hash) as intake records it; "" hash for folders and unreadables."""
    if p.is_dir() or not is_candidate(p):
        return p.name, ""
    try:
        return p.name, file_hash(p)
    except OSError:
        return p.name, ""


def unnoted_inbox(root: Path, store: MetaStore) -> bool:
    """True if inbox/ holds an entry no pass has handled yet (never noted with
    this content). Placed files have left inbox/, and every leftover is noted."""
    inbox = root / "inbox"
    if not inbox.is_dir():
        return False
    return any(not store.noted(*_inbox_key(p)) for p in inbox.iterdir())


def intake(root: Path, store: MetaStore) -> list[dict]:
    remove_orphan_texts(root, store)
    items = []
    seen: dict[str, str] = {}  # hash -> name of the file marked ready in this batch
    for p in sorted((root / "inbox").iterdir(), key=lambda x: x.name):
        if p.is_dir():
            items.append(_item(p.name, "skipped", "subfolder"))
            continue
        if not is_candidate(p):
            items.append(_item(p.name, "skipped", "not_candidate"))
            continue
        try:
            h = file_hash(p)
        except OSError as e:
            items.append(
                _item(p.name, "extract_failed", f"read_failed: {type(e).__name__}")
            )
            continue
        existing = store.by_hash(h)
        if existing:
            items.append(_item(p.name, "duplicate", existing[0].path, hash=h))
            continue
        if h in seen:
            items.append(_item(p.name, "duplicate", f"inbox/{seen[h]}", hash=h))
            continue
        if store.is_noted(p.name, h, "declined"):
            items.append(_item(p.name, "declined", hash=h))
            continue
        try:
            text = extract_text(p)
        except ExtractError as e:
            status = "unsupported" if e.reason == "unsupported" else "extract_failed"
            items.append(_item(p.name, status, e.reason, hash=h))
            continue
        doc_id = new_id()
        tp = save_text(root, doc_id, text)
        seen[h] = p.name
        item = _item(p.name, "ready", id=doc_id, hash=h, text_path=str(tp))
        noted = store.noted(p.name, h)  # e.g. name_collision on an earlier pass
        item["seen"] = bool(noted)
        item["reason"] = noted[-1] if noted else ""
        items.append(item)
    for item in items:
        if item["status"] != "ready":
            item["seen"] = store.is_noted(item["name"], item["hash"], item["status"])
    return items


def _move(src: Path, dest: Path) -> None:
    if src.exists() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))


def _finish(root: Path, store: MetaStore, doc: Doc, src: Path, dest: Path) -> None:
    _move(src, dest)
    doc.state = "active"
    store.put(doc)
    store.save()
    rebuild(root, store)


def place(
    root: Path,
    store: MetaStore,
    name: str,
    dest_rel: str,
    doc_id: str,
    hash: str,
    date: str,
    summary: str,
) -> Doc:
    dest_rel = existing_spelling(root, clamp_dest(dest_rel))
    _check_name(root, name)
    src = root / "inbox" / name
    dest = root / dest_rel / name
    if not src.is_file():
        raise SourceMissing(name)
    try:
        taken = dest.exists()
    except OSError as e:  # a name the file system cannot hold, e.g. ':' on Windows
        raise PlaceFailed(f"{dest_rel}/{name}") from e
    if taken:
        raise NameCollision(f"{dest_rel}/{name}")
    doc = Doc(
        id=doc_id,
        hash=hash,
        path=f"{dest_rel}/{name}",
        date=date,
        summary=summary,
        state="placing",
    )
    store.put(doc)
    store.save()
    try:
        _move(src, dest)
    except OSError as e:
        # Not moved: leave no "placing" record that every later resume would retry.
        store.remove(doc.id)
        store.save()
        raise PlaceFailed(doc.path) from e
    _finish(root, store, doc, src, dest)
    return doc


def resume_placing(root: Path, store: MetaStore) -> list[str]:
    resumed = []
    for doc in [d for d in store.docs() if d.state == "placing"]:
        dest = root / doc.path
        src = root / "inbox" / dest.name
        if dest.exists():
            ok = dest.is_file() and file_hash(dest) == doc.hash
        else:
            ok = src.is_file()
        if ok:
            try:
                _move(src, dest)
            except OSError:  # unmovable: drop the record; the original stays in inbox/
                store.remove(doc.id)
                store.save()
                continue
            _finish(root, store, doc, src, dest)
            resumed.append(doc.id)
        else:
            store.remove(doc.id)
            store.save()
    return resumed

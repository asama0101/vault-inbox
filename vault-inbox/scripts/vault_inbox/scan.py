from __future__ import annotations

import contextlib
from pathlib import Path

from .extract import ExtractError, extract_text, is_candidate
from .index import rebuild, save_text
from .meta import Doc, MetaStore, file_hash, new_id
from .vault import SUPPORTED_EXTS, vault_parts


def _disk_files(root: Path) -> list[str]:
    found = []
    for top in ("project", "shared"):
        base = root / top
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or not is_candidate(p):
                continue
            # Same rule as watch.snapshot: vault_parts refuses dot folders, so a file
            # in one could be reported forever and never resolved.
            if any(part.startswith(".") for part in p.relative_to(base).parts[:-1]):
                continue
            if p.suffix.lower() in SUPPORTED_EXTS:
                found.append(p.relative_to(root).as_posix())
    return found


def _refresh_text(root: Path, doc_id: str, path: str) -> None:
    # rebuild() falls back to the previous text, or skips the doc
    with contextlib.suppress(ExtractError, OSError):
        save_text(root, doc_id, extract_text(root / path))


def scan(root: Path, store: MetaStore) -> dict:
    active = [d for d in store.docs() if d.state == "active"]
    known_paths = {d.path for d in store.docs()}
    result: dict = {
        "moved": [],
        "updated": [],
        "duplicates": [],
        "unresolved": [],
        "failed": [],
    }
    changed = False
    text_changed = False

    missing = [d for d in active if not (root / d.path).is_file()]
    missing_ids = {d.id for d in missing}

    new_files: list[tuple[str, str]] = []
    for rel in _disk_files(root):
        doc = store.by_path(rel)
        try:
            h = file_hash(root / rel)
        except OSError:
            continue
        if doc is not None:
            if doc.state == "active" and doc.hash != h:
                try:
                    text = extract_text(root / rel)
                except (ExtractError, OSError) as e:
                    reason = (
                        e.reason
                        if isinstance(e, ExtractError)
                        else f"read_failed: {type(e).__name__}"
                    )
                    result["failed"].append({"path": rel, "reason": reason})
                    continue
                doc.hash = h
                store.put(doc)
                save_text(root, doc.id, text)
                result["updated"].append({"id": doc.id, "path": rel})
                changed = text_changed = True
        elif rel not in known_paths and not store.is_ignored(rel, h):
            new_files.append((rel, h))

    unmatched_new = []
    claimed: set[str] = set()
    for rel, h in new_files:
        same_missing = [d for d in missing if d.hash == h]
        if same_missing:
            unmatched_new.append((rel, h))
            continue
        same_live = [d for d in active if d.hash == h and d.id not in missing_ids]
        if same_live:
            if not store.notified_dup(rel, h):
                result["duplicates"].append({"path": rel, "same_as": same_live[0].path})
                store.mark_dup(rel, h)
                changed = True
            continue
        unmatched_new.append((rel, h))

    for d in missing:
        candidates = [(rel, h) for rel, h in unmatched_new if h == d.hash]
        others = [x for x in missing if x.hash == d.hash]
        if (
            len(candidates) == 1
            and len(others) == 1
            and candidates[0][0] not in claimed
        ):
            rel = candidates[0][0]
            claimed.add(rel)
            result["moved"].append({"id": d.id, "from": d.path, "to": rel})
            d.path = rel
            store.put(d)
            changed = True
    moved_ids = {m["id"] for m in result["moved"]}
    missing = [d for d in missing if d.id not in moved_ids]
    left_new = [
        {"path": rel, "hash": h} for rel, h in unmatched_new if rel not in claimed
    ]
    left_missing = [{"id": d.id, "path": d.path} for d in missing]
    if left_missing and left_new:
        result["unresolved"].append(
            {"kind": "missing_and_new", "missing": left_missing, "new": left_new}
        )
    else:
        result["unresolved"].extend({"kind": "missing", **m} for m in left_missing)
        result["unresolved"].extend({"kind": "new", **n} for n in left_new)

    if changed:
        store.save()
    if text_changed:
        rebuild(root, store)
    return result


def _bad_path(root: Path, store: MetaStore, rel: str, own_id: str | None) -> bool:
    """Outside project/ or shared/, or already claimed by another active doc."""
    try:
        parts = vault_parts(rel)
    except ValueError:
        return True
    top = (root / parts[0]).resolve()
    target = (root / rel).resolve()
    if top not in target.parents:
        return True
    other = store.by_path(rel)
    return other is not None and other.state == "active" and other.id != own_id


def resolve(root: Path, store: MetaStore, action: str, **kw) -> dict:
    out: dict = {"ok": True}
    required = {
        "regroup": ("missing_id", "new_path"),
        "drop": ("id",),
        "ignore": ("path",),
        "register": ("path", "date"),
    }
    if action not in required:
        return {"error": "unknown_action"}
    if any(kw.get(k) is None for k in required[action]):
        return {"error": "missing_argument"}
    file_arg = kw.get("new_path") if action == "regroup" else kw.get("path")
    if action != "drop" and _bad_path(root, store, file_arg, kw.get("missing_id")):
        return {"error": "bad_path"}
    if file_arg is not None and action != "drop" and not (root / file_arg).is_file():
        return {"error": "file_missing"}
    if action == "regroup":
        doc = store.get(kw["missing_id"])
        if doc is None:
            return {"error": "unknown_id"}
        doc.path = kw["new_path"]
        doc.hash = file_hash(root / kw["new_path"])
        store.put(doc)
        _refresh_text(root, doc.id, doc.path)
        store.save()
        rebuild(root, store)
    elif action == "drop":
        store.remove(kw["id"])
        store.save()
        rebuild(root, store)
    elif action == "ignore":
        store.ignore(kw["path"], file_hash(root / kw["path"]))
        store.save()
    elif action == "register":
        doc = Doc(
            id=new_id(),
            hash=file_hash(root / kw["path"]),
            path=kw["path"],
            date=kw["date"],
            summary=kw.get("summary", ""),
        )
        store.put(doc)
        _refresh_text(root, doc.id, doc.path)
        store.save()
        rebuild(root, store)
        out["id"] = doc.id
    return out

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_inbox import (
    extract,  # noqa: E402
    index,  # noqa: E402
    indexmd,  # noqa: E402
    relations,  # noqa: E402
    vault,  # noqa: E402
)
from vault_inbox import lock as locking  # noqa: E402
from vault_inbox import place as placing  # noqa: E402
from vault_inbox import scan as follow  # noqa: E402
from vault_inbox import watch as watching  # noqa: E402
from vault_inbox.meta import MetaStore  # noqa: E402


def _cmd_init(args) -> dict:
    root = vault.find_root(Path(args.root))
    created = vault.init_layout(root)
    return {"created": created, "has_obsidian": vault.has_obsidian(root)}


def _cmd_status(args) -> dict:
    root = vault.find_root(Path(args.root))
    return {
        "initialized": vault.is_initialized(root),
        "has_obsidian": vault.has_obsidian(root),
        "missing_deps": extract.missing_dependencies(),
    }


def _store(args) -> tuple[Path, MetaStore]:
    root = vault.find_root(Path(args.root))
    store = MetaStore(root)
    store.load()
    return root, store


def _cmd_intake(args) -> dict:
    root, store = _store(args)
    return {"items": placing.intake(root, store)}


def _cmd_place(args) -> dict:
    root, store = _store(args)
    try:
        doc = placing.place(
            root,
            store,
            args.name,
            args.dest,
            args.id,
            args.hash,
            args.date,
            args.summary,
        )
    except placing.NameCollision:
        return {"error": "name_collision"}
    except placing.SourceMissing:
        return {"error": "source_missing"}
    except placing.BadName:
        return {"error": "bad_name"}
    except placing.PlaceFailed:
        return {"error": "place_failed"}
    except ValueError:
        return {"error": "bad_destination"}
    return {"doc": asdict(doc)}


def _cmd_inbox_mark(args) -> dict:
    root, store = _store(args)
    store.note_inbox(args.name, args.hash, args.status)
    store.save()
    # An id from intake whose doc was never placed: its text file is an orphan.
    if args.id and re.fullmatch(r"[0-9A-Za-z_-]+", args.id) and not store.get(args.id):
        (index.text_dir(root) / f"{args.id}.txt").unlink(missing_ok=True)
    return {"ok": True}


def _cmd_changed(args) -> dict:
    """Also true for inbox files no pass has handled, e.g. ones dropped while a
    question was open."""
    root, store = _store(args)
    pending = placing.unnoted_inbox(root, store)
    return {"changed": watching.changed(root) or pending}


def _cmd_resume(args) -> dict:
    root, store = _store(args)
    return {"resumed": placing.resume_placing(root, store)}


def _cmd_scan(args) -> dict:
    root, store = _store(args)
    return follow.scan(root, store)


def _cmd_resolve(args) -> dict:
    root, store = _store(args)
    kw = {
        "missing_id": args.missing_id,
        "new_path": args.new_path,
        "id": args.id,
        "path": args.path,
        "date": args.date,
        "summary": args.summary,
    }
    return follow.resolve(root, store, args.action, **kw)


def _docs(store: MetaStore, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        d = store.get(i)
        if d:
            out.append({"id": d.id, "path": d.path, "summary": d.summary})
    return out


def _cmd_search(args) -> dict:
    root, store = _store(args)
    index.ensure(root, store)
    ids = index.search(root, store, args.query)
    return {"ids": ids, "docs": _docs(store, ids)}


def _cmd_expand(args) -> dict:
    _, store = _store(args)
    result = relations.expand(store, [i for i in args.ids.split(",") if i])
    return {**result, "docs": _docs(store, result["materials"])}


def _active(store: MetaStore, id: str) -> bool:
    doc = store.get(id)
    return doc is not None and doc.state == "active"


def _cmd_relate(args) -> dict:
    _, store = _store(args)
    if not (_active(store, args.src) and _active(store, args.dst)):
        return {"error": "unknown_id"}
    try:
        store.add_relation(args.src, args.dst, args.kind)
    except ValueError:
        return {"error": "unknown_kind"}
    store.save()
    return {"ok": True}


def _cmd_relation_remove(args) -> dict:
    _, store = _store(args)
    store.remove_relation(args.src, args.dst, args.kind)
    store.save()
    return {"ok": True}


def _cmd_relation_keep(args) -> dict:
    _, store = _store(args)
    store.keep_relation(args.src, args.dst, args.kind)
    store.save()
    return {"ok": True}


def _cmd_kind_add(args) -> dict:
    _, store = _store(args)
    store.add_kind(args.kind)
    store.save()
    return {"ok": True}


def _cmd_kinds(args) -> dict:
    _, store = _store(args)
    return {"kinds": store.vocabulary()}


def _cmd_update_meta(args) -> dict:
    _, store = _store(args)
    if not store.update_doc(args.id, date=args.date, summary=args.summary):
        return {"error": "unknown_id"}
    store.save()
    return {"ok": True}


def _cmd_dangling(args) -> dict:
    _, store = _store(args)
    return {"relations": relations.dangling(store)}


def _cmd_rebuild(args) -> dict:
    root, store = _store(args)
    return {"rebuilt": index.rebuild(root, store)}


def _cmd_indexmd(args) -> dict:
    root, store = _store(args)
    written = indexmd.write_notes(root, store)
    watching.absorb_recorded(root)  # our own rewrites are not edits for watch
    return {"written": written}


def _cmd_lock(args) -> dict:
    root = vault.find_root(Path(args.root))
    acquired = locking.acquire(root, args.owner, name=args.name)
    held = None if acquired else locking.holder(root, args.name)
    return {"acquired": acquired, "holder": held}


def _cmd_unlock(args) -> dict:
    locking.release(vault.find_root(Path(args.root)), args.owner, args.name)
    return {"ok": True}


def _cmd_snapshot_save(args) -> dict:
    watching.save_baseline(vault.find_root(Path(args.root)))
    return {"ok": True}


def _cmd_snapshot_absorb(args) -> dict:
    root, store = _store(args)
    active = {d.path for d in store.docs() if d.state == "active"}
    watching.absorb_own_writes(root, active)
    return {"ok": True}


def _watch_stale_after(interval: float) -> float:
    """The heartbeat touches the lock every interval; a kill leaves it unrefreshed."""
    return max(30.0, 6 * interval)


def _cmd_watch(args) -> dict | None:
    """Long-running: prints plain CHANGED lines (not JSON), one per settled change."""
    root = vault.find_root(Path(args.root))
    if not locking.acquire(root, "watch", _watch_stale_after(args.interval)):
        return {"error": "already_running"}
    # Our own token: if this watch is ever taken over as stale, it must not touch or
    # release the lock the new holder now owns.
    token = (locking.holder(root) or {}).get("token")
    try:
        watching.save_baseline(root)

        def heartbeat() -> None:
            locking.touch(root, "watch", token=token)

        for line in watching.poll(
            root, args.interval, args.settle, heartbeat=heartbeat
        ):
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    finally:
        locking.release(root, "watch", token=token)
    return None


def register(subparsers) -> None:
    """Add the subcommands of this task group."""
    for name, func in (("lock", _cmd_lock), ("unlock", _cmd_unlock)):
        p = subparsers.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--owner", required=True, choices=locking.OWNERS)
        p.add_argument("--name", default="session", choices=tuple(locking.NAMES))
        p.set_defaults(func=func)
    ip = subparsers.add_parser("inbox-mark")
    ip.add_argument("--root", default=".")
    for opt in ("name", "hash", "status"):
        ip.add_argument(f"--{opt}", required=True)
    ip.add_argument("--id")
    ip.set_defaults(func=_cmd_inbox_mark)
    cp = subparsers.add_parser("changed")
    cp.add_argument("--root", default=".")
    cp.set_defaults(func=_cmd_changed)
    sp = subparsers.add_parser("snapshot-save")
    sp.add_argument("--root", default=".")
    sp.set_defaults(func=_cmd_snapshot_save)
    ap = subparsers.add_parser("snapshot-absorb")
    ap.add_argument("--root", default=".")
    ap.set_defaults(func=_cmd_snapshot_absorb)
    wp = subparsers.add_parser("watch")
    wp.add_argument("--root", default=".")
    wp.add_argument("--interval", type=float, default=5.0)
    wp.add_argument("--settle", type=float, default=3.0)
    wp.set_defaults(func=_cmd_watch)
    sp = subparsers.add_parser("scan")
    sp.add_argument("--root", default=".")
    sp.set_defaults(func=_cmd_scan)
    rp = subparsers.add_parser("resolve")
    rp.add_argument("--root", default=".")
    rp.add_argument("--action", required=True)
    for opt in ("missing-id", "new-path", "id", "path", "date"):
        rp.add_argument(f"--{opt}")
    rp.add_argument("--summary", default="")
    rp.set_defaults(func=_cmd_resolve)
    up = subparsers.add_parser("update-meta")
    up.add_argument("--root", default=".")
    up.add_argument("--id", required=True)
    for opt in ("date", "summary"):
        up.add_argument(f"--{opt}")
    up.set_defaults(func=_cmd_update_meta)
    kp = subparsers.add_parser("kinds")
    kp.add_argument("--root", default=".")
    kp.set_defaults(func=_cmd_kinds)
    for name, func, opts in (
        ("search", _cmd_search, ("query",)),
        ("expand", _cmd_expand, ("ids",)),
        ("relate", _cmd_relate, ("src", "dst", "kind")),
        ("relation-remove", _cmd_relation_remove, ("src", "dst", "kind")),
        ("relation-keep", _cmd_relation_keep, ("src", "dst", "kind")),
        ("kind-add", _cmd_kind_add, ("kind",)),
        ("dangling", _cmd_dangling, ()),
    ):
        p = subparsers.add_parser(name)
        p.add_argument("--root", default=".")
        for opt in opts:
            p.add_argument(f"--{opt}", required=True)
        p.set_defaults(func=func)
    for name, func in (
        ("init", _cmd_init),
        ("status", _cmd_status),
        ("intake", _cmd_intake),
        ("place", _cmd_place),
        ("resume", _cmd_resume),
        ("indexmd", _cmd_indexmd),
        ("rebuild", _cmd_rebuild),
    ):
        p = subparsers.add_parser(name)
        p.add_argument("--root", default=".")
        if name == "place":
            p.add_argument("--name", required=True)
            p.add_argument("--dest", required=True)
            p.add_argument("--id", required=True)
            p.add_argument("--hash", required=True)
            p.add_argument("--date", required=True)
            p.add_argument("--summary", default="")
        p.set_defaults(func=func)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault_inbox")
    sub = parser.add_subparsers(dest="cmd", required=True)
    register(sub)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    result = args.func(args)
    if result is not None:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

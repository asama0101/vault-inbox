from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import write
from vault_inbox import index, relations
from vault_inbox.meta import Doc, MetaStore, file_hash


def _store(vault, ids="abcd", inactive=()):
    store = MetaStore(vault)
    for i in ids:
        store.put(
            Doc(
                id=i,
                hash=i,
                path=f"p/{i}.md",
                date="2026-01-01",
                summary="",
                state="placing" if i in inactive else "active",
            )
        )
    return store


def test_expand_with_no_relations_returns_hits(vault):
    store = _store(vault)
    assert relations.expand(store, ["a", "b"]) == {
        "materials": ["a", "b"],
        "conflicts": [],
    }


def test_expand_one_hop_both_directions(vault):
    store = _store(vault)
    store.add_relation("a", "b", "derived_from")
    store.add_relation("b", "c", "related")
    assert relations.expand(store, ["b"])["materials"] == ["b", "a", "c"]


def test_expand_does_not_reach_two_hops(vault):
    store = _store(vault)
    store.add_relation("a", "b", "related")
    store.add_relation("b", "c", "related")
    assert relations.expand(store, ["a"])["materials"] == ["a", "b"]


def test_expand_drops_superseded_even_when_direct_hit(vault):
    store = _store(vault)
    store.add_relation("a", "b", "supersedes")
    assert relations.expand(store, ["b", "a"])["materials"] == ["a"]
    assert relations.expand(store, ["b"])["materials"] == ["a"]


def test_expand_reports_conflicts(vault):
    store = _store(vault)
    store.add_relation("a", "b", "conflicts_with")
    store.add_relation("c", "d", "conflicts_with")
    assert relations.expand(store, ["a"])["conflicts"] == [["a", "b"]]


def test_expand_skips_dangling_relations(vault):
    store = _store(vault, inactive="b")
    store.add_relation("a", "b", "related")
    assert relations.expand(store, ["a"])["materials"] == ["a"]


def test_dangling_after_drop(vault):
    store = _store(vault)
    store.add_relation("a", "b", "related")
    store.add_relation("a", "c", "related")
    store.remove("b")
    assert relations.dangling(store) == [{"src": "a", "dst": "b", "kind": "related"}]


def test_dangling_includes_placing_and_unknown_skips_kept(vault):
    store = _store(vault, inactive="b")
    store.add_relation("a", "b", "related")
    store.add_relation("zz", "a", "supports")
    store.add_relation("c", "zz", "related")
    store.keep_relation("c", "zz", "related")
    assert relations.dangling(store) == [
        {"src": "a", "dst": "b", "kind": "related"},
        {"src": "zz", "dst": "a", "kind": "supports"},
    ]


CLI = Path(__file__).resolve().parents[1] / "scripts" / "vault_inbox.py"


def _run(vault, *args):
    r = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(CLI),
            args[0],
            "--root",
            str(vault),
            *args[1:],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0
    return json.loads(r.stdout)


def test_cli_relate_unknown_kind_then_kind_add(vault):
    _store(vault, "ab").save()
    assert _run(vault, "relate", "--src", "a", "--dst", "b", "--kind", "cites") == {
        "error": "unknown_kind"
    }
    assert _run(vault, "kind-add", "--kind", "cites") == {"ok": True}
    assert _run(vault, "relate", "--src", "a", "--dst", "b", "--kind", "cites") == {
        "ok": True
    }
    out = _run(vault, "expand", "--ids", "a")
    assert out["materials"] == ["a", "b"]
    assert out["docs"][1] == {"id": "b", "path": "p/b.md", "summary": ""}
    assert _run(vault, "dangling") == {"relations": []}
    assert _run(
        vault, "relation-remove", "--src", "a", "--dst", "b", "--kind", "cites"
    ) == {"ok": True}
    assert _run(vault, "expand", "--ids", "a")["materials"] == ["a"]


def test_cli_search_builds_index_first(vault):
    store = _store(vault, "a")
    write(vault / "p" / "a.md", "service agreement")
    index.save_text(vault, "a", "service agreement")
    store.save()
    assert _run(vault, "search", "--query", "agreement")["ids"] == ["a"]


def test_cli_relate_rejects_unknown_or_inactive_ids(vault):
    _store(vault, "abc", inactive="c").save()
    for src, dst in (("a", "zz"), ("zz", "a"), ("a", "c")):
        assert _run(
            vault, "relate", "--src", src, "--dst", dst, "--kind", "related"
        ) == {"error": "unknown_id"}
    assert _run(vault, "dangling") == {"relations": []}


def _placed(vault, store, doc_id, rel, text):
    write(vault / rel, text)
    store.put(Doc(doc_id, file_hash(vault / rel), rel, "2026-01-01", "s"))
    index.save_text(vault, doc_id, text)


def test_cli_drop_then_dangling_then_keep_or_remove(vault):
    store = MetaStore(vault)
    _placed(vault, store, "a", "project/x/a.md", "alpha")
    _placed(vault, store, "b", "project/y/b.md", "bravo")
    _placed(vault, store, "c", "project/y/c.md", "charlie")
    store.save()
    for src in ("a", "c"):
        assert _run(
            vault, "relate", "--src", src, "--dst", "b", "--kind", "related"
        ) == {"ok": True}
    (vault / "project/y/b.md").unlink()
    unresolved = _run(vault, "scan")["unresolved"]
    assert unresolved == [{"kind": "missing", "id": "b", "path": "project/y/b.md"}]
    assert _run(vault, "resolve", "--action", "drop", "--id", "b") == {"ok": True}
    assert _run(vault, "dangling") == {
        "relations": [
            {"src": "a", "dst": "b", "kind": "related"},
            {"src": "c", "dst": "b", "kind": "related"},
        ]
    }
    assert _run(
        vault, "relation-keep", "--src", "a", "--dst", "b", "--kind", "related"
    ) == {"ok": True}
    assert _run(
        vault, "relation-remove", "--src", "c", "--dst", "b", "--kind", "related"
    ) == {"ok": True}
    assert _run(vault, "dangling") == {"relations": []}
    s = MetaStore(vault)
    s.load()
    assert s.relations() == [{"src": "a", "dst": "b", "kind": "related", "kept": True}]

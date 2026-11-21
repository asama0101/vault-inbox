from __future__ import annotations

import json
from pathlib import Path

import pytest
from vault_inbox.meta import Doc, MetaCorrupt, MetaStore


def make_doc(id: str = "a", hash: str = "h1", path: str = "inbox/a.md") -> Doc:
    return Doc(id=id, hash=hash, path=path, date="2026-11-21", summary="要約")


def test_save_load_roundtrip(vault: Path):
    s = MetaStore(vault)
    s.put(make_doc())
    s.put(make_doc("b", "h2", "inbox/b.md"))
    s.add_relation("a", "b", "related")
    s.add_kind("cites")
    s.ignore("inbox/x.md", "hx")
    s.mark_dup("inbox/y.md", "hy")
    s.save()
    raw = (vault / ".vault-inbox" / "meta.json").read_text(encoding="utf-8")
    assert "要約" in raw  # ensure_ascii=False

    t = MetaStore(vault)
    t.load()
    assert t.get("a") == make_doc()
    assert t.get("b").path == "inbox/b.md"
    assert t.relations() == [{"src": "a", "dst": "b", "kind": "related"}]
    assert "cites" in t.vocabulary()
    assert t.is_ignored("inbox/x.md", "hx")
    assert t.notified_dup("inbox/y.md", "hy")
    assert t.by_hash("h2")[0].id == "b"


def test_initial_vocabulary_is_fixed_five(vault: Path):
    assert MetaStore(vault).vocabulary() == [
        "derived_from",
        "supersedes",
        "supports",
        "conflicts_with",
        "related",
    ]


def test_save_keeps_bak_of_previous_version(vault: Path):
    s = MetaStore(vault)
    s.put(make_doc())
    s.save()
    s.put(make_doc("b", "h2", "inbox/b.md"))
    s.save()
    bak = json.loads(
        (vault / ".vault-inbox" / "meta.json.bak").read_text(encoding="utf-8")
    )
    assert list(bak["docs"]) == ["a"]


def test_load_falls_back_to_bak_when_main_corrupt(vault: Path):
    s = MetaStore(vault)
    s.put(make_doc())
    s.save()
    s.put(make_doc("b", "h2", "inbox/b.md"))
    s.save()
    (vault / ".vault-inbox" / "meta.json").write_text("{broken", encoding="utf-8")
    t = MetaStore(vault)
    t.load()
    assert t.get("a") is not None


def test_load_raises_when_corrupt_and_no_bak(vault: Path):
    (vault / ".vault-inbox" / "meta.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(MetaCorrupt):
        MetaStore(vault).load()


def test_load_without_files_is_empty(vault: Path):
    s = MetaStore(vault)
    s.load()
    assert s.docs() == []


def test_remove_keeps_relations(vault: Path):
    s = MetaStore(vault)
    s.put(make_doc())
    s.put(make_doc("b", "h2", "inbox/b.md"))
    s.put(make_doc("c", "h3", "inbox/c.md"))
    s.add_relation("a", "b", "related")
    s.add_relation("c", "a", "supports")
    s.add_relation("b", "c", "related")
    s.remove("a")
    assert s.get("a") is None
    assert len(s.relations()) == 3


def test_keep_relation_is_persisted(vault: Path):
    s = MetaStore(vault)
    s.add_relation("a", "b", "related")
    assert s.keep_relation("a", "b", "related") is True
    assert s.keep_relation("a", "b", "supports") is False
    s.add_relation("a", "b", "related")  # no duplicate of a kept relation
    s.save()
    t = MetaStore(vault)
    t.load()
    assert t.relations() == [{"src": "a", "dst": "b", "kind": "related", "kept": True}]
    t.remove_relation("a", "b", "related")
    assert t.relations() == []


def test_add_relation_rejects_unknown_kind(vault: Path):
    s = MetaStore(vault)
    with pytest.raises(ValueError, match="unknown relation kind"):
        s.add_relation("a", "b", "cites")
    assert s.relations() == []


def test_add_relation_ignores_duplicates_and_remove_relation(vault: Path):
    s = MetaStore(vault)
    s.add_relation("a", "b", "related")
    s.add_relation("a", "b", "related")
    assert len(s.relations()) == 1
    s.remove_relation("a", "b", "related")
    assert s.relations() == []


def test_add_kind_then_relation_ok(vault: Path):
    s = MetaStore(vault)
    s.add_kind("cites")
    s.add_relation("a", "b", "cites")
    assert s.relations() == [{"src": "a", "dst": "b", "kind": "cites"}]


def test_ignore_is_keyed_by_path_and_hash(vault: Path):
    s = MetaStore(vault)
    s.ignore("inbox/a.md", "h1")
    assert s.is_ignored("inbox/a.md", "h1")
    assert not s.is_ignored("inbox/a.md", "h2")
    assert not s.is_ignored("inbox/b.md", "h1")


def test_by_path_uses_posix_separators(vault: Path):
    s = MetaStore(vault)
    s.put(make_doc(path="project/案件 X/資料.pdf"))
    assert s.by_path("project/案件 X/資料.pdf").id == "a"
    assert s.by_path("project\\案件 X\\資料.pdf").id == "a"
    s.put(make_doc("b", "h2", "project\\案件 Y\\b.pdf"))
    assert s.get("b").path == "project/案件 Y/b.pdf"


@pytest.mark.parametrize(
    "bad_doc",
    [
        {"id": "a", "hash": "h1"},  # missing fields
        {**vars(make_doc()), "extra": 1},  # unexpected field
        ["not", "a", "dict"],
    ],
)
def test_doc_with_wrong_fields_is_corrupt(vault: Path, bad_doc):
    s = MetaStore(vault)
    s.put(make_doc())
    s.save()
    s.save()  # now meta.json.bak holds the good version
    main = vault / ".vault-inbox" / "meta.json"
    data = json.loads(main.read_text(encoding="utf-8"))
    data["docs"] = {"a": bad_doc}
    main.write_text(json.dumps(data), encoding="utf-8")
    t = MetaStore(vault)
    t.load()
    assert t.get("a") == make_doc()
    (vault / ".vault-inbox" / "meta.json.bak").unlink()
    with pytest.raises(MetaCorrupt):
        MetaStore(vault).load()


def test_a_meta_file_of_an_older_version_with_tags_still_loads(vault: Path):
    old = {
        "docs": {
            "a": {
                "id": "a",
                "hash": "h1",
                "path": "project/a.md",
                "date": "2026-01-01",
                "tags": ["契約", "2026"],
                "summary": "要約",
                "state": "active",
            }
        },
        "relations": [],
    }
    (vault / ".vault-inbox" / "meta.json").write_text(
        json.dumps(old, ensure_ascii=False), encoding="utf-8"
    )
    s = MetaStore(vault)
    s.load()
    assert s.get("a") == Doc("a", "h1", "project/a.md", "2026-01-01", "要約")
    s.save()
    saved = json.loads((vault / ".vault-inbox" / "meta.json").read_text("utf-8"))
    assert "tags" not in saved["docs"]["a"]


def test_a_doc_with_an_unknown_field_is_still_rejected(vault: Path):
    bad = {
        "docs": {
            "a": {
                "id": "a",
                "hash": "h",
                "path": "p",
                "date": "d",
                "summary": "s",
                "colour": "red",
            }
        }
    }
    (vault / ".vault-inbox" / "meta.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(MetaCorrupt):
        MetaStore(vault).load()

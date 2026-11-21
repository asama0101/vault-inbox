import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import write
from vault_inbox.index import load_text, save_text, search
from vault_inbox.meta import Doc, MetaStore, file_hash
from vault_inbox.relations import dangling
from vault_inbox.scan import resolve, scan

CLI = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"


def add(vault, store, rel, text, doc_id="d1"):
    write(vault / rel, text)
    store.put(Doc(doc_id, file_hash(vault / rel), rel, "2026-01-01", "s"))
    save_text(vault, doc_id, text)
    store.save()


def fresh(vault):
    s = MetaStore(vault)
    s.load()
    return s


def test_moved_when_hash_same_path_changed(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a/議事録 1.md", "same body", "d1")
    add(vault, store, "project/b.md", "other", "d2")
    store.add_relation("d1", "d2", "related")
    (vault / "project/新 フォルダ").mkdir()
    (vault / "project/a/議事録 1.md").rename(vault / "project/新 フォルダ/議事録 1.md")
    r = scan(vault, store)
    assert r["moved"] == [
        {
            "id": "d1",
            "from": "project/a/議事録 1.md",
            "to": "project/新 フォルダ/議事録 1.md",
        }
    ]
    assert r["unresolved"] == []
    s = fresh(vault)
    assert s.get("d1").path == "project/新 フォルダ/議事録 1.md"
    assert s.relations() == [{"src": "d1", "dst": "d2", "kind": "related"}]


def test_renamed_in_same_folder(vault):
    store = MetaStore(vault)
    add(vault, store, "shared/a.md", "body")
    (vault / "shared/a.md").rename(vault / "shared/b.md")
    r = scan(vault, store)
    assert r["moved"] == [{"id": "d1", "from": "shared/a.md", "to": "shared/b.md"}]


def test_updated_when_hash_changed_in_place(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "old content")
    write(vault / "project/a.md", "brand new zebra content")
    r = scan(vault, store)
    assert r["updated"] == [{"id": "d1", "path": "project/a.md"}]
    assert r["moved"] == []
    assert r["unresolved"] == []
    assert fresh(vault).get("d1").hash == file_hash(vault / "project/a.md")
    assert load_text(vault, "d1") == "brand new zebra content"
    assert search(vault, store, "zebra") == ["d1"]


def test_unresolved_missing_and_new_when_edited_and_moved(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "old")
    (vault / "project/a.md").unlink()
    write(vault / "project/sub/a2.md", "edited")
    r = scan(vault, store)
    assert r["moved"] == []
    assert r["updated"] == []
    assert r["unresolved"] == [
        {
            "kind": "missing_and_new",
            "missing": [{"id": "d1", "path": "project/a.md"}],
            "new": [
                {
                    "path": "project/sub/a2.md",
                    "hash": file_hash(vault / "project/sub/a2.md"),
                }
            ],
        }
    ]


def test_unresolved_missing_only_when_deleted(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "old")
    (vault / "project/a.md").unlink()
    assert scan(vault, store)["unresolved"] == [
        {"kind": "missing", "id": "d1", "path": "project/a.md"}
    ]


def test_unresolved_new_when_user_drops_file_in_project(vault):
    store = MetaStore(vault)
    write(vault / "project/n.md", "fresh")
    h = file_hash(vault / "project/n.md")
    assert scan(vault, store)["unresolved"] == [
        {"kind": "new", "path": "project/n.md", "hash": h}
    ]
    assert store.docs() == []


def test_duplicate_copy_reported_once(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "body")
    write(vault / "shared/copy.md", "body")
    r = scan(vault, store)
    assert r["duplicates"] == [{"path": "shared/copy.md", "same_as": "project/a.md"}]
    assert r["unresolved"] == []
    r2 = scan(vault, fresh(vault))
    assert r2["duplicates"] == []
    assert r2["unresolved"] == []
    assert len(fresh(vault).docs()) == 1


def test_ambiguous_hash_goes_to_unresolved(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "body")
    (vault / "project/a.md").unlink()
    write(vault / "project/x.md", "body")
    write(vault / "project/y.md", "body")
    r = scan(vault, store)
    assert r["moved"] == []
    assert r["unresolved"][0]["kind"] == "missing_and_new"
    assert len(r["unresolved"][0]["new"]) == 2


def test_index_md_and_unsupported_files_are_ignored(vault):
    store = MetaStore(vault)
    write(vault / "project/_index.md", "idx")
    write(vault / "project/x.doc", "bin")
    write(vault / "project/~$a.docx", "tmp")
    write(vault / "inbox/a.md", "in inbox")
    assert scan(vault, store) == {
        "moved": [],
        "updated": [],
        "duplicates": [],
        "unresolved": [],
        "failed": [],
    }


def test_files_in_hidden_folders_are_ignored(vault):
    """.obsidian/.git/.trash can never be registered (vault_parts refuses them),
    so scan must not ask about them on every pass."""
    store = MetaStore(vault)
    write(vault / "project/.obsidian/note.md", "settings-like note")
    write(vault / "shared/docs/.trash/old.md", "deleted note")
    write(vault / "project/.hidden.md", "hidden file")
    assert scan(vault, store)["unresolved"] == []


def test_placing_docs_are_not_considered(vault):
    store = MetaStore(vault)
    store.put(Doc("p", "h", "project/gone.md", "2026-01-01", "", state="placing"))
    assert scan(vault, store)["unresolved"] == []


def test_regroup_keeps_id_and_relations(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "old", "d1")
    add(vault, store, "project/b.md", "other", "d2")
    store.add_relation("d1", "d2", "related")
    (vault / "project/a.md").unlink()
    write(vault / "project/新 a.md", "edited quokka")
    assert resolve(
        vault, store, "regroup", missing_id="d1", new_path="project/新 a.md"
    ) == {"ok": True}
    s = fresh(vault)
    assert s.get("d1").path == "project/新 a.md"
    assert s.get("d1").hash == file_hash(vault / "project/新 a.md")
    assert s.relations() == [{"src": "d1", "dst": "d2", "kind": "related"}]
    assert load_text(vault, "d1") == "edited quokka"
    assert scan(vault, s)["unresolved"] == []


def test_drop_keeps_relations_as_dangling_and_keeps_file(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "keep me", "d1")
    add(vault, store, "project/b.md", "other", "d2")
    store.add_relation("d1", "d2", "related")
    assert resolve(vault, store, "drop", id="d1") == {"ok": True}
    s = fresh(vault)
    assert s.get("d1") is None
    assert dangling(s) == [{"src": "d1", "dst": "d2", "kind": "related"}]
    assert (vault / "project/a.md").exists()
    assert search(vault, s, "keep me") == []


def test_ignore_suppresses_until_hash_or_path_changes(vault):
    store = MetaStore(vault)
    write(vault / "project/n.md", "v1")
    assert resolve(vault, store, "ignore", path="project/n.md") == {"ok": True}
    assert scan(vault, fresh(vault))["unresolved"] == []
    write(vault / "project/n.md", "v2")
    assert scan(vault, fresh(vault))["unresolved"][0]["kind"] == "new"
    write(vault / "project/n.md", "v1")
    (vault / "project/n.md").rename(vault / "project/m.md")
    assert scan(vault, fresh(vault))["unresolved"][0]["path"] == "project/m.md"


def test_register_in_place(vault):
    store = MetaStore(vault)
    write(vault / "project/n.md", "narwhal text")
    r = resolve(
        vault,
        store,
        "register",
        path="project/n.md",
        date="2026-02-02",
        summary="s",
    )
    assert r["ok"] is True
    d = fresh(vault).get(r["id"])
    assert (d.path, d.state, d.date) == ("project/n.md", "active", "2026-02-02")
    assert d.hash == file_hash(vault / "project/n.md")
    assert search(vault, store, "narwhal") == [r["id"]]
    assert scan(vault, fresh(vault))["unresolved"] == []


def test_scan_is_idempotent(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "one", "d1")
    add(vault, store, "project/b.md", "two", "d2")
    (vault / "project/a.md").rename(vault / "project/a2.md")
    write(vault / "project/b.md", "two changed")
    write(vault / "project/c.md", "two changed")
    first = scan(vault, store)
    assert len(first["moved"]) == 1
    assert len(first["updated"]) == 1
    second = scan(vault, fresh(vault))
    assert second["moved"] == []
    assert second["updated"] == []
    assert second["duplicates"] == []


def test_cli_scan_and_resolve(vault):
    write(vault / "project/n.md", "x")

    def run(*args):
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), *args, "--root", str(vault)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    assert run("scan")["unresolved"][0]["kind"] == "new"
    assert run("resolve", "--action", "ignore", "--path", "project/n.md") == {
        "ok": True
    }
    assert run("scan")["unresolved"] == []


def test_ignored_file_with_missing_doc_hash_is_not_listed_or_moved(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "body")
    (vault / "project/a.md").unlink()
    write(vault / "project/x.md", "body")
    store.ignore("project/x.md", file_hash(vault / "project/x.md"))
    r = scan(vault, store)
    assert r["moved"] == []
    assert r["unresolved"] == [{"kind": "missing", "id": "d1", "path": "project/a.md"}]


def test_ignored_file_is_not_a_move_target_when_another_copy_exists(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "body")
    (vault / "project/a.md").unlink()
    write(vault / "project/x.md", "body")
    write(vault / "project/y.md", "body")
    store.ignore("project/x.md", file_hash(vault / "project/x.md"))
    r = scan(vault, store)
    assert r["moved"] == [{"id": "d1", "from": "project/a.md", "to": "project/y.md"}]
    assert r["unresolved"] == []


def test_failed_extraction_keeps_doc_and_retries(vault):
    store = MetaStore(vault)
    add(vault, store, "project/a.md", "old")
    old_hash = store.get("d1").hash
    write(vault / "project/a.md", "")
    r = scan(vault, store)
    assert r["updated"] == []
    assert [f["path"] for f in r["failed"]] == ["project/a.md"]
    assert r["failed"][0]["reason"]
    assert fresh(vault).get("d1").hash == old_hash
    write(vault / "project/a.md", "repaired text")
    r2 = scan(vault, fresh(vault))
    assert r2["updated"] == [{"id": "d1", "path": "project/a.md"}]
    assert r2["failed"] == []
    assert load_text(vault, "d1") == "repaired text"


def test_cli_resolve_bad_input_returns_json_error(vault):
    def run(*args):
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), *args, "--root", str(vault)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    write(vault / "project/n.md", "x")
    assert run("resolve", "--action", "ignore", "--path", "project/nope.md") == {
        "error": "file_missing"
    }
    assert run("resolve", "--action", "ignore") == {"error": "missing_argument"}
    assert run(
        "resolve",
        "--action",
        "register",
        "--path",
        "project/nope.md",
        "--date",
        "2026-01-01",
    ) == {"error": "file_missing"}
    assert run(
        "resolve",
        "--action",
        "regroup",
        "--missing-id",
        "zz",
        "--new-path",
        "project/n.md",
    ) == {"error": "unknown_id"}


@pytest.mark.parametrize(
    "bad",
    [
        "project/../../x.md",
        "project/../inbox/a.md",
        "project/.obsidian/x.md",
        "inbox/a.md",
        "project",
        "..\\x.md",
        "project\\a.md",
        "ABS",
    ],
)
@pytest.mark.parametrize("action", ["register", "ignore", "regroup"])
def test_resolve_rejects_paths_outside_project_or_shared(vault, bad, action):
    store = MetaStore(vault)
    add(vault, store, "project/gone.md", "gone", "d1")
    (vault / "project/gone.md").unlink()
    write(vault / "inbox/a.md", "x")
    write(vault / "project/a.md", "x")
    write(vault / "project/.obsidian/x.md", "x")
    write(vault.parent / "x.md", "x")
    path = str(vault / "project" / "a.md") if bad == "ABS" else bad
    kw = {"missing_id": "d1", "new_path": path} if action == "regroup" else {}
    if action != "regroup":
        kw = {"path": path, "date": "2026-01-01"}
    assert resolve(vault, store, action, **kw) == {"error": "bad_path"}


def test_resolve_rejects_path_of_another_active_doc(vault):
    store = MetaStore(vault)
    add(vault, store, "project/gone.md", "gone", "d1")
    add(vault, store, "project/b.md", "bee", "d2")
    (vault / "project/gone.md").unlink()
    for action, kw in (
        ("regroup", {"missing_id": "d1", "new_path": "project/b.md"}),
        ("register", {"path": "project/b.md", "date": "2026-01-01"}),
        ("ignore", {"path": "project/b.md"}),
    ):
        assert resolve(vault, store, action, **kw) == {"error": "bad_path"}, action
    assert fresh(vault).get("d2").path == "project/b.md"


def test_generated_notes_and_hidden_index_are_ignored(vault):
    store = MetaStore(vault)
    write(vault / "project/x/.index.md", "idx")
    write(vault / "project/x/a.md.要約.md", "note")
    assert scan(vault, store)["unresolved"] == []

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import write
from vault_inbox.meta import Doc, MetaStore, file_hash
from vault_inbox.place import (
    BadName,
    NameCollision,
    PlaceFailed,
    SourceMissing,
    clamp_dest,
    intake,
    place,
    resume_placing,
)

CLI = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"


def by_name(items):
    return {i["name"]: i for i in items}


def test_clamp_dest_truncates_to_five():
    assert clamp_dest("project/a/b/c/d/e/f") == "project/a/b/c/d"


def test_clamp_dest_keeps_five_components():
    assert clamp_dest("project/a/b/c/d") == "project/a/b/c/d"


def test_clamp_dest_rejects_other_roots():
    with pytest.raises(ValueError, match="bad destination"):
        clamp_dest("inbox/a")


def test_intake_ready_and_text_saved(vault):
    write(vault / "inbox" / "a.md", "hello world")
    store = MetaStore(vault)
    item = intake(vault, store)[0]
    assert item["status"] == "ready"
    assert item["id"]
    assert item["hash"] == file_hash(vault / "inbox" / "a.md")
    assert Path(item["text_path"]).read_text(encoding="utf-8") == "hello world"


def test_intake_duplicate_of_registered(vault):
    write(vault / "inbox" / "a.md", "same")
    store = MetaStore(vault)
    store.put(
        Doc(
            "x",
            file_hash(vault / "inbox" / "a.md"),
            "project/old.md",
            "2026-01-01",
            "",
        )
    )
    item = intake(vault, store)[0]
    assert item["status"] == "duplicate"
    assert item["reason"] == "project/old.md"


def test_intake_duplicate_within_same_batch(vault):
    write(vault / "inbox" / "a.md", "same")
    write(vault / "inbox" / "b.md", "same")
    items = by_name(intake(vault, MetaStore(vault)))
    assert items["a.md"]["status"] == "ready"
    assert items["b.md"]["status"] == "duplicate"


def test_intake_unsupported_and_extract_failed_stay(vault):
    (vault / "inbox" / "x.doc").write_bytes(b"abc")
    (vault / "inbox" / "bad.pdf").write_bytes(b"not a pdf")
    (vault / "inbox" / "empty.md").write_bytes(b"")
    items = by_name(intake(vault, MetaStore(vault)))
    assert items["x.doc"]["status"] == "unsupported"
    assert items["bad.pdf"]["status"] == "extract_failed"
    assert items["bad.pdf"]["reason"]
    assert items["empty.md"]["status"] == "extract_failed"
    assert items["empty.md"]["reason"] == "empty"
    assert all((vault / "inbox" / n).exists() for n in items)


def test_intake_whitespace_only_is_extract_failed(vault):
    write(vault / "inbox" / "w.md", "  \n\t ")
    item = intake(vault, MetaStore(vault))[0]
    assert item["status"] == "extract_failed"
    assert item["reason"] == "empty"


def test_intake_skips_office_temp_and_subfolders(vault):
    (vault / "inbox" / "~$a.docx").write_bytes(b"x")
    (vault / "inbox" / ".hidden").write_bytes(b"x")
    (vault / "inbox" / "sub").mkdir()
    items = by_name(intake(vault, MetaStore(vault)))
    assert {i["status"] for i in items.values()} == {"skipped"}
    assert items["sub"]["reason"] == "subfolder"


def _ready(vault, name, text):
    write(vault / "inbox" / name, text)
    store = MetaStore(vault)
    return store, intake(vault, store)[0]


def test_place_moves_original_unchanged(vault):
    store, it = _ready(vault, "a.md", "本文 content")
    before = file_hash(vault / "inbox" / "a.md")
    doc = place(
        vault,
        store,
        "a.md",
        "project/x/y",
        it["id"],
        it["hash"],
        "2026-01-01",
        "s",
    )
    assert not (vault / "inbox" / "a.md").exists()
    assert file_hash(vault / "project/x/y/a.md") == before == doc.hash
    assert doc.path == "project/x/y/a.md"
    assert doc.state == "active"
    fresh = MetaStore(vault)
    fresh.load()
    assert fresh.get(it["id"]).state == "active"


def test_place_name_collision_leaves_inbox_file(vault):
    store, it = _ready(vault, "a.md", "new")
    write(vault / "project" / "x" / "a.md", "different")
    with pytest.raises(NameCollision):
        place(
            vault,
            store,
            "a.md",
            "project/x",
            it["id"],
            it["hash"],
            "2026-01-01",
            "",
        )
    assert (vault / "inbox" / "a.md").read_text(encoding="utf-8") == "new"
    assert store.get(it["id"]) is None


def test_place_japanese_name_with_spaces(vault):
    store, it = _ready(vault, "議事録 2026 final.md", "内容")
    doc = place(
        vault,
        store,
        "議事録 2026 final.md",
        "shared/会議 資料",
        it["id"],
        it["hash"],
        "2026-01-01",
        "",
    )
    assert doc.path == "shared/会議 資料/議事録 2026 final.md"
    assert (vault / doc.path).exists()


def test_resume_after_crash_between_move_and_register(vault):
    store, it = _ready(vault, "a.md", "text")
    write(vault / "project" / "a.md", "text")
    (vault / "inbox" / "a.md").unlink()
    store.put(
        Doc(it["id"], it["hash"], "project/a.md", "2026-01-01", "", state="placing")
    )
    assert resume_placing(vault, store) == [it["id"]]
    fresh = MetaStore(vault)
    fresh.load()
    assert fresh.get(it["id"]).state == "active"


def test_resume_when_original_still_in_inbox(vault):
    store, it = _ready(vault, "a.md", "text")
    store.put(
        Doc(it["id"], it["hash"], "project/a.md", "2026-01-01", "", state="placing")
    )
    assert resume_placing(vault, store) == [it["id"]]
    assert (vault / "project" / "a.md").exists()
    assert not (vault / "inbox" / "a.md").exists()
    assert store.get(it["id"]).state == "active"


def test_resume_removes_when_original_gone(vault):
    store = MetaStore(vault)
    store.put(Doc("g", "h", "project/a.md", "2026-01-01", "", state="placing"))
    assert resume_placing(vault, store) == []
    assert store.get("g") is None


def test_place_identical_content_at_dest_is_collision(vault):
    store, it = _ready(vault, "a.md", "same")
    write(vault / "project" / "x" / "a.md", "same")
    with pytest.raises(NameCollision):
        place(
            vault,
            store,
            "a.md",
            "project/x",
            it["id"],
            it["hash"],
            "2026-01-01",
            "",
        )
    assert (vault / "inbox" / "a.md").exists()
    assert store.get(it["id"]) is None


def test_place_source_missing_registers_nothing(vault):
    store = MetaStore(vault)
    with pytest.raises(SourceMissing):
        place(vault, store, "nope.md", "project/x", "i", "h", "2026-01-01", "")
    write(vault / "project" / "x" / "nope.md", "x")
    with pytest.raises(SourceMissing):
        place(vault, store, "nope.md", "project/x", "i", "h", "2026-01-01", "")
    assert store.docs() == []


def test_resume_drops_doc_when_dest_differs_and_src_exists(vault):
    store, it = _ready(vault, "a.md", "mine")
    write(vault / "project" / "a.md", "someone else")
    store.put(
        Doc(it["id"], it["hash"], "project/a.md", "2026-01-01", "", state="placing")
    )
    assert resume_placing(vault, store) == []
    assert store.get(it["id"]) is None
    assert (vault / "inbox" / "a.md").read_text(encoding="utf-8") == "mine"
    assert (vault / "project" / "a.md").read_text(encoding="utf-8") == "someone else"


def test_cli_place_source_missing_exit_zero(vault):
    r = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(CLI),
            "place",
            "--root",
            str(vault),
            "--name",
            "a.md",
            "--dest",
            "project/x",
            "--id",
            "i",
            "--hash",
            "h",
            "--date",
            "2026-01-01",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"error": "source_missing"}


def test_cli_place_collision_exit_zero(vault):
    write(vault / "inbox" / "a.md", "new")
    write(vault / "project" / "x" / "a.md", "other")
    r = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(CLI),
            "place",
            "--root",
            str(vault),
            "--name",
            "a.md",
            "--dest",
            "project/x",
            "--id",
            "i",
            "--hash",
            "h",
            "--date",
            "2026-01-01",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"error": "name_collision"}


def test_note_inbox_is_persisted(vault):
    store = MetaStore(vault)
    store.note_inbox("a.md", "h", "duplicate")
    store.note_inbox("a.md", "h", "duplicate")
    store.save()
    s = MetaStore(vault)
    s.load()
    assert s.is_noted("a.md", "h", "duplicate") is True
    assert s.is_noted("a.md", "h2", "duplicate") is False
    assert s.is_noted("a.md", "h", "unsupported") is False
    assert s.is_noted("b.md", "h", "duplicate") is False


def test_intake_non_ready_items_carry_seen(vault):
    (vault / "inbox" / "x.doc").write_bytes(b"abc")
    (vault / "inbox" / "sub").mkdir()
    store = MetaStore(vault)
    items = by_name(intake(vault, store))
    assert items["x.doc"]["seen"] is False
    assert items["sub"]["seen"] is False
    for i in items.values():
        store.note_inbox(i["name"], i["hash"], i["status"])
    again = by_name(intake(vault, store))
    assert again["x.doc"]["seen"] is True
    assert again["sub"]["seen"] is True
    (vault / "inbox" / "x.doc").write_bytes(b"changed")
    assert by_name(intake(vault, store))["x.doc"]["seen"] is False


def test_intake_declined_until_content_changes(vault):
    write(vault / "inbox" / "a.md", "hello")
    store = MetaStore(vault)
    first = intake(vault, store)[0]
    store.note_inbox("a.md", first["hash"], "declined")
    item = intake(vault, store)[0]
    assert (item["status"], item["seen"], item["id"]) == ("declined", True, "")
    write(vault / "inbox" / "a.md", "hello again")
    assert intake(vault, store)[0]["status"] == "ready"


def test_repeated_intake_leaves_no_orphan_texts(vault):
    store, placed = _ready(vault, "p.md", "placed body")
    place(vault, store, "p.md", "project/x", placed["id"], placed["hash"], "", "")
    write(vault / "inbox" / "a.md", "hello")
    for _ in range(3):
        last = by_name(intake(vault, store))["a.md"]
    texts = sorted(p.stem for p in (vault / ".vault-inbox" / "text").iterdir())
    assert texts == sorted([placed["id"], last["id"]])


def _cli(vault, *args):
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(CLI), args[0], "--root", str(vault)]
        + list(args[1:]),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_cli_inbox_mark_declined_removes_orphan_text(vault):
    write(vault / "inbox" / "a.md", "hello")
    item = _cli(vault, "intake")["items"][0]
    assert Path(item["text_path"]).is_file()
    assert _cli(
        vault,
        "inbox-mark",
        "--name=a.md",
        f"--hash={item['hash']}",
        "--status=declined",
        f"--id={item['id']}",
    ) == {"ok": True}
    assert not Path(item["text_path"]).exists()
    again = _cli(vault, "intake")["items"][0]
    assert (again["status"], again["seen"]) == ("declined", True)


def test_cli_inbox_mark_keeps_text_of_placed_doc(vault):
    store, item = _ready(vault, "a.md", "body")
    place(vault, store, "a.md", "project/x", item["id"], item["hash"], "", "")
    assert _cli(
        vault,
        "inbox-mark",
        "--name=a.md",
        "--hash=h",
        "--status=declined",
        f"--id={item['id']}",
    ) == {"ok": True}
    assert Path(item["text_path"]).is_file()


def test_cli_inbox_mark_without_id_and_bad_id(vault):
    assert _cli(
        vault, "inbox-mark", "--name=x.doc", "--hash=", "--status=unsupported"
    ) == {"ok": True}
    assert _cli(
        vault,
        "inbox-mark",
        "--name=x",
        "--hash=h",
        "--status=declined",
        "--id=../meta",
    ) == {"ok": True}
    assert (vault / ".vault-inbox" / "meta.json").is_file()


def test_place_reuses_existing_folder_spelling(vault):
    """Foo and foo are one folder on Windows/macOS; two spellings in meta.json would
    write two sets of notes into it and drop one folder's."""
    store = MetaStore(vault)
    docs = []
    for name, dest in (("a.md", "project/Foo/Bar"), ("b.md", "project/foo/bar")):
        write(vault / "inbox" / name, name)
        it = next(i for i in intake(vault, store) if i["name"] == name)
        docs.append(place(vault, store, name, dest, it["id"], it["hash"], "", ""))
    assert [d.path for d in docs] == ["project/Foo/Bar/a.md", "project/Foo/Bar/b.md"]
    assert sorted(p.name for p in (vault / "project").iterdir()) == ["Foo"]


def _blocked_dest(vault):
    """A destination that cannot be created: a path component is a regular file."""
    write(vault / "project" / "f", "not a folder")
    return "project/f/sub"


def test_place_unmovable_dest_registers_nothing(vault):
    store, it = _ready(vault, "a.md", "text")
    with pytest.raises(PlaceFailed):
        place(vault, store, "a.md", _blocked_dest(vault), it["id"], it["hash"], "", "")
    assert (vault / "inbox" / "a.md").is_file()
    assert store.get(it["id"]) is None
    fresh = MetaStore(vault)
    fresh.load()
    assert fresh.docs() == []  # no "placing" left behind to trip resume


def test_resume_drops_placing_doc_whose_move_fails(vault):
    store, it = _ready(vault, "a.md", "text")
    store.put(
        Doc(
            it["id"],
            it["hash"],
            _blocked_dest(vault) + "/a.md",
            "2026-01-01",
            "",
            state="placing",
        )
    )
    assert resume_placing(vault, store) == []
    assert store.get(it["id"]) is None
    assert (vault / "inbox" / "a.md").is_file()


def test_cli_place_unmovable_dest_returns_error(vault):
    write(vault / "inbox" / "a.md", "text")
    item = _cli(vault, "intake")["items"][0]
    out = _cli(
        vault,
        "place",
        "--name=a.md",
        f"--dest={_blocked_dest(vault)}",
        f"--id={item['id']}",
        f"--hash={item['hash']}",
        "--date=2026-01-01",
    )
    assert out == {"error": "place_failed"}
    assert _cli(vault, "resume") == {"resumed": []}


def test_intake_skips_generated_index_file(vault):
    write(vault / "inbox" / "_index.md", "my own note")
    item = intake(vault, MetaStore(vault))[0]
    assert (item["status"], item["reason"]) == ("skipped", "not_candidate")


def test_place_rejects_index_file_name(vault):
    write(vault / "inbox" / "_index.md", "my own note")
    with pytest.raises(BadName):
        place(vault, MetaStore(vault), "_index.md", "project/x", "i", "h", "", "")
    assert (vault / "inbox" / "_index.md").is_file()


def test_cli_changed(vault):
    assert _cli(vault, "changed") == {"changed": False}
    assert _cli(vault, "snapshot-save") == {"ok": True}
    assert _cli(vault, "changed") == {"changed": False}
    write(vault / "inbox" / "n.md", "new")
    assert _cli(vault, "changed") == {"changed": True}


@pytest.mark.parametrize(
    "dest",
    [
        "project",
        "shared/",
        "project/a/",
        "project//a",
        "project/./a",
        "project/../../x",
        "project/a/../../../x",
        "project/.obsidian/x",
        "/project/x",
        "project\\x",
        "..\\project\\x",
        "C:/project/x",
    ],
)
def test_clamp_dest_rejects_unsafe(dest):
    with pytest.raises(ValueError, match="destination"):
        clamp_dest(dest)


def _place_cli(vault, name, dest):
    return _cli(
        vault,
        "place",
        f"--name={name}",
        f"--dest={dest}",
        "--id=i",
        "--hash=h",
        "--date=2026-01-01",
    )


def test_cli_place_rejects_traversal_destination(vault):
    write(vault / "inbox" / "a.md", "x")
    for dest in ("project/../../x", "project/.obsidian/x", "project"):
        assert _place_cli(vault, "a.md", dest) == {"error": "bad_destination"}
    assert (vault / "inbox" / "a.md").is_file()


@pytest.mark.parametrize("name", ["../a.md", "sub/a.md", "sub\\a.md", "..", ".", ""])
def test_cli_place_rejects_bad_name(vault, name):
    write(vault / "a.md", "outside inbox")
    write(vault / "inbox" / "sub" / "a.md", "in a subfolder")
    assert _place_cli(vault, name, "project/x") == {"error": "bad_name"}
    assert not (vault / "project" / "x").exists()


def _pass_end(vault):
    assert _cli(vault, "indexmd")
    assert _cli(vault, "snapshot-save") == {"ok": True}


def test_cli_changed_true_for_inbox_file_dropped_during_a_pass(vault):
    write(vault / "inbox" / "a.md", "alpha")
    assert _cli(vault, "snapshot-save") == {"ok": True}
    item = _cli(vault, "intake")["items"][0]
    write(vault / "inbox" / "x.md", "dropped while a question was open")
    placed = _cli(
        vault,
        "place",
        "--name=a.md",
        "--dest=project/p",
        f"--id={item['id']}",
        f"--hash={item['hash']}",
        "--date=2026-01-01",
    )
    assert "doc" in placed
    _pass_end(vault)  # the baseline now contains x.md
    assert _cli(vault, "changed") == {"changed": True}


def test_cli_changed_false_after_own_writes_and_noted_leftovers(vault):
    write(vault / "inbox" / "a.md", "alpha")
    (vault / "inbox" / "x.doc").write_bytes(b"old format")
    assert _cli(vault, "snapshot-save") == {"ok": True}
    items = by_name(_cli(vault, "intake")["items"])
    a, x = items["a.md"], items["x.doc"]
    assert "doc" in _cli(
        vault,
        "place",
        "--name=a.md",
        "--dest=project/p",
        f"--id={a['id']}",
        f"--hash={a['hash']}",
        "--date=2026-01-01",
    )
    assert _cli(
        vault,
        "inbox-mark",
        "--name=x.doc",
        f"--hash={x['hash']}",
        "--status=unsupported",
    ) == {"ok": True}
    _pass_end(vault)
    assert _cli(vault, "changed") == {"changed": False}


def test_intake_ready_item_noted_as_collision_is_seen_with_reason(vault):
    write(vault / "inbox" / "a.md", "hello")
    store = MetaStore(vault)
    first = intake(vault, store)[0]
    assert (first["status"], first["seen"]) == ("ready", False)
    store.note_inbox("a.md", first["hash"], "name_collision")
    again = intake(vault, store)[0]
    assert (again["status"], again["seen"], again["reason"]) == (
        "ready",
        True,
        "name_collision",
    )
    assert again["id"]  # still placeable: a manual organize retries it
    write(vault / "inbox" / "a.md", "hello changed")
    assert intake(vault, store)[0]["seen"] is False


def test_cli_inbox_mark_collision_removes_orphan_text(vault):
    write(vault / "inbox" / "a.md", "hello")
    item = _cli(vault, "intake")["items"][0]
    assert _cli(
        vault,
        "inbox-mark",
        "--name=a.md",
        f"--hash={item['hash']}",
        "--status=name_collision",
        f"--id={item['id']}",
    ) == {"ok": True}
    assert not Path(item["text_path"]).exists()
    assert _cli(vault, "changed") == {"changed": False}


def _start_pass_with_doc(vault):
    """A registered doc project/x/x.md, one file in inbox/, baseline at start."""
    write(vault / "inbox" / "a.md", "alpha")
    write(vault / "project" / "x" / "x.md", "x body")
    assert "id" in _cli(
        vault,
        "resolve",
        "--action=register",
        "--path=project/x/x.md",
        "--date=2026-01-01",
    )
    assert _cli(vault, "snapshot-save") == {"ok": True}  # pass start
    return _cli(vault, "intake")["items"][0]


def _place_and_finish(vault, item):
    assert "doc" in _cli(
        vault,
        "place",
        "--name=a.md",
        "--dest=project/p",
        f"--id={item['id']}",
        f"--hash={item['hash']}",
        "--date=2026-01-01",
    )
    assert _cli(vault, "indexmd")
    assert _cli(vault, "snapshot-absorb") == {"ok": True}  # pass end


def test_pass_own_writes_alone_do_not_trigger(vault):
    _place_and_finish(vault, _start_pass_with_doc(vault))
    assert _cli(vault, "changed") == {"changed": False}


@pytest.mark.parametrize("change", ["edit", "move", "delete", "new"])
def test_user_change_in_project_during_pass_is_detected(vault, change):
    item = _start_pass_with_doc(vault)
    x = vault / "project" / "x" / "x.md"
    if change == "edit":
        write(x, "x body edited while a question was open")
    elif change == "move":
        (vault / "project" / "y").mkdir()
        x.rename(vault / "project" / "y" / "x.md")
    elif change == "delete":
        x.unlink()
    else:
        write(vault / "shared" / "s" / "new.md", "put there by hand")
    _place_and_finish(vault, item)
    assert _cli(vault, "changed") == {"changed": True}


def test_skipped_leftover_recorded_with_empty_hash_is_not_pending(vault):
    (vault / "inbox" / "sub").mkdir()
    assert _cli(vault, "snapshot-save") == {"ok": True}
    item = _cli(vault, "intake")["items"][0]
    assert (item["status"], item["hash"]) == ("skipped", "")
    assert _cli(vault, "inbox-mark", "--name=sub", "--hash=", "--status=skipped") == {
        "ok": True
    }
    assert _cli(vault, "changed") == {"changed": False}


def test_unnoted_inbox_without_inbox_folder_is_false(tmp_path):
    from vault_inbox.place import unnoted_inbox

    assert unnoted_inbox(tmp_path, MetaStore(tmp_path)) is False


def test_intake_and_place_refuse_generated_note_names(vault):
    write(vault / "inbox" / "a.md.要約.md", "my own note")
    item = intake(vault, MetaStore(vault))[0]
    assert (item["status"], item["reason"]) == ("skipped", "not_candidate")
    with pytest.raises(BadName):
        place(vault, MetaStore(vault), "a.md.要約.md", "project/x", "i", "h", "", "")

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import write
from vault_inbox import indexmd
from vault_inbox.meta import Doc, MetaStore


def _put(store, id, path, summary="", state="active", on_disk=True):
    if on_disk:
        write(store._file.parents[1] / path, id)
    store.put(
        Doc(
            id=id,
            hash=id,
            path=path,
            date="2026-01-01",
            summary=summary,
            state=state,
        )
    )


def _read(vault, rel):
    return (vault / rel).read_text(encoding="utf-8")


def test_link_for_obsidian_openable_vs_office():
    assert (
        indexmd.link_for("project/a/契約 書.pdf")
        == "[[project/a/契約 書.pdf|契約 書.pdf]]"
    )
    assert indexmd.link_for("project/a/note.md") == "[[project/a/note.md|note.md]]"
    assert indexmd.link_for("project/a/見積.docx") == "見積.docx"
    assert indexmd.link_for("project/a/memo.txt") == "memo.txt"
    assert indexmd.link_for("project/a/page.html") == "page.html"


def test_link_for_is_plain_text_when_a_character_would_break_the_link():
    for name in ("a]]b.md", "a#b.md", "a^b.md", "a[b.md", "a|b.md"):
        assert indexmd.link_for(f"project/x/{name}") == name
    assert indexmd.link_for("project/a#b/c.md") == "c.md"  # also for a folder name


def test_no_folder_index_is_written_any_more(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    _put(store, "b", "project/x/y/b.pdf")
    written = indexmd.write_notes(vault, store)
    assert written == ["project/x/y/b.pdf.要約.md"]  # only notes are returned
    assert not list(vault.rglob("*index.md"))


def test_a_summary_with_line_breaks_stays_one_line_in_the_property(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf", "一行目\n- 偽の項目\n\n続き")
    indexmd.write_notes(vault, store)
    assert '要約: "一行目 - 偽の項目 続き"\n' in _note(vault, "project/x/a.pdf")


def test_same_name_in_two_folders_gets_distinct_links(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/案件A/議事録.pdf")
    _put(store, "b", "project/案件B/議事録.pdf")
    store.add_relation("a", "b", "related")
    indexmd.write_notes(vault, store)
    assert "[[project/案件B/議事録.pdf.要約.md|related → 議事録.pdf]]" in _note(
        vault, "project/案件A/議事録.pdf"
    )
    assert "[[project/案件A/議事録.pdf.要約.md|related ← 議事録.pdf]]" in _note(
        vault, "project/案件B/議事録.pdf"
    )


def test_a_doc_outside_project_and_shared_gets_no_note(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    _put(store, "b", "inbox/b.pdf")
    written = indexmd.write_notes(vault, store)
    assert written == ["project/x/a.pdf.要約.md"]
    assert not (vault / "inbox" / ("b.pdf" + indexmd.NOTE_SUFFIX)).exists()


def test_a_note_is_regenerated_over_hand_edits(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf", "s")
    indexmd.write_notes(vault, store)
    note = _note_path(vault, "project/x/a.pdf")
    note.write_text(note.read_text(encoding="utf-8") + "手編集", encoding="utf-8")
    indexmd.write_notes(vault, store)
    assert "手編集" not in note.read_text(encoding="utf-8")


def test_cli_indexmd(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    _put(store, "b", "project/x/b.pdf")
    store.save()
    cli = Path(__file__).resolve().parents[1] / "scripts" / "vault_inbox.py"
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(cli), "indexmd", "--root", str(vault)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"written": ["project/x/b.pdf.要約.md"]}


def test_stale_metadata_creates_no_folder_or_note(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/gone/a.pdf", on_disk=False)
    _put(store, "b", "project/x/b.pdf")
    _put(store, "c", "project/x/c.pdf", on_disk=False)
    written = indexmd.write_notes(vault, store)
    assert written == ["project/x/b.pdf.要約.md"]
    assert not (vault / "project/gone").exists()
    assert not _note_path(vault, "project/x/c.pdf").exists()


def test_relation_with_missing_or_inactive_end_not_listed(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    _put(store, "m", "project/x/m.pdf", on_disk=False)
    _put(store, "p", "project/x/p.pdf", state="placing")
    store.add_relation("a", "m", "related")
    store.add_relation("p", "a", "related")
    indexmd.write_notes(vault, store)
    assert "関連:" not in _note(vault, "project/x/a.pdf")


def test_relation_links_are_sorted_and_deduplicated(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    _put(store, "b", "project/x/b.pdf")
    _put(store, "c", "project/x/c.pdf")
    store.add_relation("c", "a", "related")
    store.add_relation("a", "b", "related")
    store.add_relation("a", "b", "related")
    indexmd.write_notes(vault, store)
    lines = [x for x in _note(vault, "project/x/a.pdf").splitlines() if "[[" in x][:2]
    assert lines == [
        '  - "[[project/x/b.pdf.要約.md|related → b.pdf]]"',
        '  - "[[project/x/c.pdf.要約.md|related ← c.pdf]]"',
    ]


def test_folder_indexes_of_older_versions_are_removed_when_they_are_ours(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    write(
        vault / "project/x/_index.md", "# x\n\n## 資料\n\n- [[project/x/a.md|a.md]]\n"
    )
    write(vault / "project/x/.index.md", f"{indexmd._MARK}\n# x\n\n## 資料\n\n- a\n")
    write(vault / "project/.index.md", "自分の隠しメモ")  # a person's: no mark
    indexmd.write_notes(vault, store)
    assert not (vault / "project/x/_index.md").exists()
    assert not (vault / "project/x/.index.md").exists()
    assert _read(vault, "project/.index.md") == "自分の隠しメモ"


def _note(vault, doc_path):
    return _read(vault, doc_path + indexmd.NOTE_SUFFIX)


def _note_path(vault, doc_path):
    return vault / (doc_path + indexmd.NOTE_SUFFIX)


def test_non_markdown_doc_gets_a_summary_note_with_properties(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/案件A/契約.pdf", "契約の要約")
    indexmd.write_notes(vault, store)
    note = _note(vault, "project/案件A/契約.pdf")
    assert note.startswith('---\n要約: "契約の要約"\n日付: 2026-01-01\n---\n')
    assert indexmd._MARK in note
    assert "[[project/案件A/契約.pdf|契約.pdf]]" in note  # note -> original
    assert _read(vault, "project/案件A/契約.pdf") == "a"  # original untouched


def test_markdown_doc_gets_its_properties_in_place_and_no_note(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "本文の要約")
    (vault / "project/x/a.md").write_bytes("本文\n".encode())
    indexmd.write_notes(vault, store)
    assert (vault / "project/x/a.md").read_bytes().decode() == (
        '---\n要約: "本文の要約"\n日付: 2026-01-01\nvault-inbox: true\n---\n本文\n'
    )
    assert not _note_path(vault, "project/x/a.md").exists()


def test_markdown_with_own_frontmatter_keeps_every_other_key(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "新しい要約")
    original = "---\ntitle: 題\ntags: [x, y]\n---\n本文\n"
    (vault / "project/x/a.md").write_bytes(original.encode())
    indexmd.write_notes(vault, store)
    text = (vault / "project/x/a.md").read_bytes().decode()
    assert text == (
        "---\ntitle: 題\ntags: [x, y]\n"
        '要約: "新しい要約"\n日付: 2026-01-01\nvault-inbox: true\n---\n本文\n'
    )


def test_markdown_properties_are_rewritten_only_when_they_change(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "s")
    indexmd.write_notes(vault, store)
    path = vault / "project/x/a.md"
    before = path.stat().st_mtime_ns
    indexmd.write_notes(vault, store)
    assert path.stat().st_mtime_ns == before
    _put(store, "a", "project/x/a.md", "変えた要約", on_disk=False)
    indexmd.write_notes(vault, store)
    assert "変えた要約" in path.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8").count("要約:") == 1


def test_our_properties_do_not_change_the_hash_but_a_body_edit_does(vault):
    from vault_inbox.meta import file_hash

    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "s")
    path = vault / "project/x/a.md"
    path.write_bytes("本文\n".encode())
    h0 = file_hash(path)
    assert h0 == hashlib.sha256("本文\n".encode()).hexdigest()  # old hashes stay valid
    indexmd.write_notes(vault, store)
    assert path.read_bytes().startswith(b"---")
    assert file_hash(path) == h0
    path.write_bytes(path.read_bytes() + "追記\n".encode())
    assert file_hash(path) != h0


def test_markdown_that_cannot_be_edited_gets_a_note_instead(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "要約")
    (vault / "project/x/a.md").write_bytes(b"\xff\xfe not utf-8")
    indexmd.write_notes(vault, store)
    assert (vault / "project/x/a.md").read_bytes() == b"\xff\xfe not utf-8"
    assert '要約: "要約"' in _note(vault, "project/x/a.md")


def test_a_failed_markdown_write_is_left_for_the_next_run(vault, monkeypatch):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "要約")
    before = (vault / "project/x/a.md").read_bytes()
    real = Path.write_bytes

    def failing(self, data):
        if self.name.endswith(".tmp"):
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing)
    indexmd.write_notes(vault, store)
    assert (vault / "project/x/a.md").read_bytes() == before
    assert not list((vault / "project/x").glob(".*.tmp"))
    assert not _note_path(vault, "project/x/a.md").exists()  # it is a retry, not a note
    monkeypatch.undo()
    indexmd.write_notes(vault, store)
    assert (vault / "project/x/a.md").read_bytes().startswith(b"---")


def test_a_material_saved_by_someone_meanwhile_is_not_overwritten(vault, monkeypatch):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "要約")
    path = vault / "project/x/a.md"
    real = shutil.copymode

    def copymode_then_user_saves(src, dst):
        real(src, dst)
        path.write_bytes(
            "利用者が今保存した内容\n".encode()
        )  # between read and replace

    monkeypatch.setattr(shutil, "copymode", copymode_then_user_saves)
    indexmd.write_notes(vault, store)
    assert path.read_bytes().decode() == "利用者が今保存した内容\n"
    assert not list((vault / "project/x").glob(".*.tmp"))


def test_the_authors_own_keys_are_never_overwritten(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "システムの要約")
    mine = "---\n日付: 2020-01-01\ntags: [mine, keep]\n関連: 手書き\n---\n本文\n"
    (vault / "project/x/a.md").write_bytes(mine.encode())
    indexmd.write_notes(vault, store)
    assert (vault / "project/x/a.md").read_bytes().decode() == mine
    assert '要約: "システムの要約"' in _note(vault, "project/x/a.md")  # a note instead


def test_a_marked_block_is_ours_and_gets_updated(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "一回目")
    indexmd.write_notes(vault, store)
    _put(store, "a", "project/x/a.md", "二回目", on_disk=False)
    indexmd.write_notes(vault, store)
    text = (vault / "project/x/a.md").read_text(encoding="utf-8")
    assert text.count("vault-inbox: true") == 1
    assert "二回目" in text
    assert not _note_path(vault, "project/x/a.md").exists()


def test_a_linked_or_read_only_markdown_gets_a_note_and_stays_as_it_is(vault):
    store = MetaStore(vault)
    _put(store, "ro", "project/x/ro.md", "読み取り専用")
    _put(store, "hl", "project/x/hl.md", "ハードリンク")
    ro, hl = vault / "project/x/ro.md", vault / "project/x/hl.md"
    os.link(hl, vault / "project/x/hl-copy.md")
    ro.chmod(stat.S_IREAD)
    try:
        indexmd.write_notes(vault, store)
    finally:
        ro.chmod(stat.S_IWRITE | stat.S_IREAD)
    assert ro.read_text(encoding="utf-8") == "ro"
    assert hl.read_text(encoding="utf-8") == "hl"
    assert _note_path(vault, "project/x/ro.md").is_file()
    assert _note_path(vault, "project/x/hl.md").is_file()
    assert not list((vault / "project/x").glob(".*.tmp"))


def test_a_note_with_a_long_frontmatter_is_still_updated_and_removed(vault):
    store = MetaStore(vault)
    _put(store, "p", "project/x/main.pdf", "親")
    for i in range(60):
        _put(store, f"d{i}", f"project/x/d{i:02d}.docx")
        store.add_relation("p", f"d{i}", "related")
    indexmd.write_notes(vault, store)
    note = _note_path(vault, "project/x/main.pdf")
    assert len(note.read_text(encoding="utf-8")) > 3000
    store.remove_relation("p", "d0", "related")  # the id of d00.docx
    indexmd.write_notes(vault, store)
    assert "d00.docx" not in note.read_text(encoding="utf-8")
    store.remove("p")
    indexmd.write_notes(vault, store)
    assert not note.exists()


def test_a_leftover_temporary_file_is_removed(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    tmp = vault / "project/x/.a.md.vault-inbox.tmp"
    write(tmp, "cut short")
    indexmd.write_notes(vault, store)
    assert not tmp.exists()


def test_the_extracted_text_of_markdown_has_none_of_our_properties(vault):
    from vault_inbox.extract import extract_text

    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "秘密の要約")
    (vault / "project/x/a.md").write_bytes("本文だけ\n".encode())
    indexmd.write_notes(vault, store)
    assert "秘密の要約" in (vault / "project/x/a.md").read_text(encoding="utf-8")
    assert extract_text(vault / "project/x/a.md") == "本文だけ\n"


def test_a_relation_recorded_outside_a_pass_does_not_look_like_an_edit(vault):
    cli = Path(__file__).resolve().parents[1] / "scripts" / "vault_inbox.py"

    def run(*args):
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(cli), *args, "--root", str(vault)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(r.stdout)

    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "s")
    store.save()
    run("snapshot-save")
    run("indexmd")  # the recording of a relation by ask runs exactly this
    assert (vault / "project/x/a.md").read_bytes().startswith(b"---")
    assert run("changed") == {"changed": False}


def test_a_second_record_keeps_the_first_before():
    import tempfile

    from vault_inbox import ownwrites

    root = Path(tempfile.mkdtemp())
    (root / ".vault-inbox").mkdir()
    ownwrites.record(root, {"p.md": [1, 10, 2, 20]})
    ownwrites.record(root, {"p.md": [2, 20, 3, 30]})
    assert ownwrites.take(root) == {"p.md": [1, 10, 3, 30]}
    assert ownwrites.take(root) == {}


def test_relations_become_links_in_the_properties_of_both_sides(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/案件A/契約.pdf")
    _put(store, "b", "project/案件A/メモ.md")
    store.add_relation("a", "b", "related")
    indexmd.write_notes(vault, store)
    note = _note(vault, "project/案件A/契約.pdf")
    assert '関連:\n  - "[[project/案件A/メモ.md|related → メモ.md]]"\n' in note
    md = (vault / "project/案件A/メモ.md").read_text(encoding="utf-8")
    assert '  - "[[project/案件A/契約.pdf.要約.md|related ← 契約.pdf]]"\n' in md


def test_every_link_in_the_properties_points_to_an_existing_file(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/案件A/契約.pdf")
    _put(store, "b", "shared/議事/メモ.txt")
    _put(store, "c", "project/案件B/見積.md")
    store.add_relation("a", "b", "related")
    store.add_relation("c", "a", "derived_from")
    indexmd.write_notes(vault, store)
    seen = 0
    for path in vault.rglob("*"):
        if path.is_file() and path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r'"\[\[([^\]|]+)\|', text):
                seen += 1
                assert (vault / target).is_file(), (path.name, target)
    assert seen >= 4


def test_note_is_removed_when_the_doc_becomes_editable_markdown_or_goes(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    indexmd.write_notes(vault, store)
    assert _note_path(vault, "project/x/a.pdf").is_file()
    store.remove("a")
    indexmd.write_notes(vault, store)
    assert not _note_path(vault, "project/x/a.pdf").exists()


def test_note_follows_a_moved_doc(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/old/a.pdf")
    indexmd.write_notes(vault, store)
    _put(store, "a", "project/new/a.pdf")
    indexmd.write_notes(vault, store)
    assert not _note_path(vault, "project/old/a.pdf").exists()
    assert "[[project/new/a.pdf|a.pdf]]" in _note(vault, "project/new/a.pdf")


def test_is_generated_covers_the_old_index_names_and_notes():
    for name in (".index.md", "_index.md", "a.pdf.要約.md"):
        assert indexmd.is_generated(name)
    for name in ("index.md", "a.md", "要約.md.txt", "a.pdf.関連.md"):
        assert not indexmd.is_generated(name)


def test_a_persons_file_with_a_generated_name_is_not_removed_or_overwritten(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf", "要約")
    mine = {
        "project/x/会議.要約.md": "自分のノート",
        "project/x/_index.md": "自分の目次",
        "project/x/a.pdf.要約.md": "自分のノート2",  # where the note of a.pdf would go
        "project/x/.index.md": "自分の隠しメモ",
    }
    for rel, text in mine.items():
        write(vault / rel, text)
    indexmd.write_notes(vault, store)
    for rel, text in mine.items():
        assert _read(vault, rel) == text


def test_a_registered_material_named_like_a_note_is_never_removed(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/議事録.要約.md", "旧版で取り込んだ資料")
    indexmd.write_notes(vault, store)
    assert (vault / "project/x/議事録.要約.md").is_file()


def test_a_folder_named_like_a_note_does_not_stop_the_run(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    _put(store, "b", "project/x/b.pdf")
    (vault / "project/x/資料.要約.md").mkdir()
    (vault / "project/x/a.pdf.要約.md").mkdir()  # even where a note would go
    indexmd.write_notes(vault, store)
    assert _note_path(vault, "project/x/b.pdf").is_file()


def test_hidden_folders_are_not_walked(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    inner = vault / "project/.git/pkg/README.要約.md"
    write(inner, f"{indexmd._MARK}\n外の資料の生成物に見える")
    indexmd.write_notes(vault, store)
    assert inner.is_file()


def test_a_note_write_that_fails_is_skipped_and_the_rest_goes_on(vault, monkeypatch):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    _put(store, "b", "project/x/b.pdf")
    real_open = Path.open

    def failing_open(self, *args, **kwargs):
        if self.name == "a.pdf" + indexmd.NOTE_SUFFIX:
            raise OSError("path too long")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    indexmd.write_notes(vault, store)
    assert not _note_path(vault, "project/x/a.pdf").exists()
    assert _note_path(vault, "project/x/b.pdf").is_file()


def test_unchanged_notes_are_not_rewritten(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf", "s")
    indexmd.write_notes(vault, store)
    note = _note_path(vault, "project/x/a.pdf")
    before = note.stat().st_mtime_ns
    indexmd.write_notes(vault, store)
    assert note.stat().st_mtime_ns == before


@pytest.mark.skipif(os.name != "nt", reason="letter case matters on other systems")
def test_folder_renamed_only_in_letter_case_keeps_its_files(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/foo/a.pdf")
    indexmd.write_notes(vault, store)
    (vault / "project/foo").rename(vault / "project/FOO")
    indexmd.write_notes(vault, store)
    assert (vault / "project/FOO/a.pdf.要約.md").is_file()


def test_a_path_with_a_link_breaking_character_gets_plain_text_not_a_link(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a#1.pdf")
    _put(store, "b", "project/x/b.pdf")
    store.add_relation("a", "b", "related")
    indexmd.write_notes(vault, store)
    assert '  - "related ← a#1.pdf"\n' in _note(vault, "project/x/b.pdf")


def test_watch_ignores_our_rewrite_of_an_untouched_markdown(vault):
    from vault_inbox import watch

    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "s")
    watch.save_baseline(vault)
    indexmd.write_notes(vault, store)
    assert watch.changed(vault) is True  # the rewrite alone
    watch.absorb_own_writes(vault, {"project/x/a.md"})
    assert watch.changed(vault) is False


def test_watch_still_sees_a_user_edit_made_before_our_rewrite(vault):
    from vault_inbox import watch

    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md", "s")
    watch.save_baseline(vault)
    write(vault / "project/x/a.md", "ユーザーが編集した")
    indexmd.write_notes(vault, store)
    watch.absorb_own_writes(vault, {"project/x/a.md"})
    assert watch.changed(vault) is True


def test_an_underscore_index_that_is_not_the_old_output_is_kept(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    # the old output began with the name of its own folder; this one does not
    write(vault / "project/x/_index.md", "# 自分の目次\n\n## 資料\n\n- 手書き\n")
    indexmd.write_notes(vault, store)
    assert "手書き" in _read(vault, "project/x/_index.md")


def test_a_file_that_only_quotes_our_mark_is_kept(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.pdf")
    quoted = f"自分のメモ。印の行はこう書く: {indexmd._MARK}\n"
    write(vault / "project/x/b.pdf.要約.md", quoted)
    write(vault / "project/x/.index.md", f"本文\n{indexmd._MARK}\n")
    indexmd.write_notes(vault, store)
    assert _read(vault, "project/x/b.pdf.要約.md") == quoted
    assert (vault / "project/x/.index.md").is_file()


def test_a_read_only_old_index_is_removed_too(vault):
    store = MetaStore(vault)
    _put(store, "a", "project/x/a.md")
    old = vault / "project/x/.index.md"
    write(old, f"{indexmd._MARK}\n# x\n")
    old.chmod(stat.S_IREAD)
    try:
        indexmd.write_notes(vault, store)
    finally:
        if old.exists():
            old.chmod(stat.S_IWRITE | stat.S_IREAD)
    assert not old.exists()

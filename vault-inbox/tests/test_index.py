from __future__ import annotations

import shutil

from conftest import write
from vault_inbox import index
from vault_inbox.meta import Doc, MetaStore


def _add(vault, store, doc_id, text, state="active", name=None):
    rel = f"project/{name or doc_id}.md"
    write(vault / rel, text)
    store.put(
        Doc(
            id=doc_id,
            hash=doc_id,
            path=rel,
            date="2026-01-01",
            summary="",
            state=state,
        )
    )
    index.save_text(vault, doc_id, text)


def _setup(vault):
    store = MetaStore(vault)
    _add(vault, store, "a", "service agreement 契約書 alpha")
    _add(vault, store, "b", "service report beta")
    _add(vault, store, "c", "契 only")
    index.rebuild(vault, store)
    return store


def test_search_three_chars_uses_fts(vault):
    store = _setup(vault)
    assert index.search(vault, store, "agreement") == ["a"]


def test_search_two_chars_japanese(vault):
    store = _setup(vault)
    assert index.search(vault, store, "契約") == ["a"]


def test_search_and_of_short_and_long_terms(vault):
    store = _setup(vault)
    assert index.search(vault, store, "service 契約") == ["a"]
    assert sorted(index.search(vault, store, "service")) == ["a", "b"]
    assert index.search(vault, store, "report 契約") == []


def test_search_special_chars_do_not_raise(vault):
    store = _setup(vault)
    assert index.search(vault, store, '"foo" (bar) -baz*') == []
    assert index.search(vault, store, "") == []


def test_rebuild_after_deleting_index_and_text(vault):
    store = _setup(vault)
    before = sorted(index.search(vault, store, "service"))
    (vault / ".vault-inbox" / "index.db").unlink()
    shutil.rmtree(vault / ".vault-inbox" / "text")
    assert index.rebuild(vault, store) == 3
    assert sorted(index.search(vault, store, "service")) == before
    assert index.search(vault, store, "契約") == ["a"]


def test_rebuild_skips_doc_with_missing_original(vault):
    store = _setup(vault)
    (vault / ".vault-inbox" / "text" / "b.txt").unlink()
    (vault / "project" / "b.md").unlink()
    assert index.rebuild(vault, store) == 2


def test_ensure_rebuilds_when_missing(vault):
    store = _setup(vault)
    assert index.ensure(vault, store) is False
    (vault / ".vault-inbox" / "index.db").unlink()
    assert index.ensure(vault, store) is True
    assert index.search(vault, store, "agreement") == ["a"]


def test_ensure_rebuilds_when_corrupt(vault):
    store = _setup(vault)
    (vault / ".vault-inbox" / "index.db").write_bytes(b"not a database" * 100)
    assert index.ensure(vault, store) is True
    assert index.search(vault, store, "agreement") == ["a"]


def test_ensure_rebuilds_when_an_active_doc_is_not_indexed(vault):
    """e.g. the pass crashed after saving meta.json but before the index update."""
    store = _setup(vault)
    _add(vault, store, "z", "zeppelin manual")
    assert index.ensure(vault, store) is True
    assert index.search(vault, store, "zeppelin") == ["z"]
    assert index.ensure(vault, store) is False


def test_ensure_does_not_rebuild_for_a_doc_that_can_never_be_indexed(vault):
    store = _setup(vault)
    store.put(Doc("n", "n", "project/n.md", "2026-01-01", ""))  # no text, no file
    assert index.ensure(vault, store) is False


def test_search_ignores_placing_docs(vault):
    store = MetaStore(vault)
    _add(vault, store, "a", "service agreement")
    _add(vault, store, "p", "service agreement", state="placing")
    index.rebuild(vault, store)
    assert index.search(vault, store, "agreement") == ["a"]
    assert index.search(vault, store, "se") == ["a"]

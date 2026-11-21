from __future__ import annotations

import threading
import time
from pathlib import Path

from conftest import write
from vault_inbox import watch


def test_snapshot_excludes_index_md_and_hidden_dirs(vault: Path):
    write(vault / "inbox" / "a.md", "a")
    write(vault / "project" / "p" / "b.md", "b")
    write(vault / "project" / "p" / "_index.md", "idx")
    write(vault / "shared" / ".files" / "x.pdf", "x")
    write(vault / "shared" / ".obsidian" / "o.json", "o")
    write(vault / "shared" / ".vault-inbox" / "v.json", "v")
    write(vault / "other" / "c.md", "c")
    write(vault / ".vault-inbox" / "meta.json", "{}")
    snap = watch.snapshot(vault)
    assert sorted(snap) == ["inbox/a.md", "project/p/b.md"]
    mtime_ns, size = snap["inbox/a.md"]
    assert size == 1
    assert mtime_ns > 0


def test_changed_false_without_baseline(vault: Path):
    write(vault / "inbox" / "a.md", "a")
    assert watch.changed(vault) is False


def test_changed_false_right_after_baseline(vault: Path):
    write(vault / "inbox" / "a.md", "a")
    watch.save_baseline(vault)
    assert watch.changed(vault) is False


def test_changed_true_after_new_file(vault: Path):
    watch.save_baseline(vault)
    write(vault / "inbox" / "new.md", "n")
    assert watch.changed(vault) is True


def test_changed_ignores_index_md_writes(vault: Path):
    watch.save_baseline(vault)
    write(vault / "project" / "_index.md", "x")
    assert watch.changed(vault) is False


def _collect(vault: Path, out: list, **kw) -> threading.Thread:
    def run():
        for line in watch.poll(vault, **kw):
            out.append((line, time.monotonic()))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_poll_waits_for_settle(vault: Path):
    watch.save_baseline(vault)
    out: list = []
    _collect(vault, out, interval=0.02, settle=0.3)
    target = vault / "inbox" / "big.md"
    last_write = 0.0
    for i in range(6):  # steps 0.1 s apart, shorter than settle
        write(target, "x" * (i + 1))
        last_write = time.monotonic()
        time.sleep(0.1)
        assert out == []
    time.sleep(0.7)
    assert [line for line, _ in out] == ["CHANGED"]
    assert out[0][1] - last_write >= 0.3


def test_poll_yields_once_for_duplicate_events(vault: Path):
    watch.save_baseline(vault)
    out: list = []
    _collect(vault, out, interval=0.02, settle=0.2)
    for name in ("a.md", "b.md", "a.md", "c.md"):
        write(vault / "inbox" / name, name + str(time.monotonic()))
    time.sleep(1.0)  # several poll cycles after settling; baseline is still old
    assert [line for line, _ in out] == ["CHANGED"]


def test_poll_once_stops_after_one_yield(vault: Path):
    watch.save_baseline(vault)
    write(vault / "inbox" / "a.md", "a")
    assert list(watch.poll(vault, interval=0.02, settle=0.1, once=True)) == ["CHANGED"]


def test_poll_once_without_change_yields_nothing(vault: Path):
    watch.save_baseline(vault)
    assert list(watch.poll(vault, interval=0.02, settle=0.1, once=True)) == []


def test_cli_lock_watch_refusal_unlock_and_snapshot_save(vault: Path, capsys):
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"
    spec = importlib.util.spec_from_file_location("vi_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(["lock", "--root", str(vault), "--owner", "watch"]) == 0
    assert '"acquired": true' in capsys.readouterr().out
    assert cli.main(["watch", "--root", str(vault)]) == 0
    assert capsys.readouterr().out.strip() == '{"error": "already_running"}'
    assert cli.main(["unlock", "--root", str(vault), "--owner", "watch"]) == 0
    assert cli.main(["snapshot-save", "--root", str(vault)]) == 0
    assert (vault / ".vault-inbox" / "watch_baseline.json").exists()


def test_poll_skips_when_baseline_saved_during_settle(vault: Path):
    watch.save_baseline(vault)
    out: list = []
    _collect(vault, out, interval=0.02, settle=0.5)
    write(vault / "inbox" / "organized.md", "x")
    time.sleep(0.15)
    watch.save_baseline(vault)  # organize finished inside the settle window
    time.sleep(1.0)
    assert out == []


def test_poll_real_change_after_suppressed_one_yields_once(vault: Path):
    watch.save_baseline(vault)
    out: list = []
    _collect(vault, out, interval=0.02, settle=0.3)
    write(vault / "inbox" / "organized.md", "x")
    time.sleep(0.1)
    watch.save_baseline(vault)
    time.sleep(0.6)
    assert out == []
    write(vault / "inbox" / "real.md", "y")
    time.sleep(1.0)
    assert [line for line, _ in out] == ["CHANGED"]


def test_snapshot_and_changed_ignore_generated_notes(vault: Path):
    write(vault / "project" / "p" / "b.md", "b")
    watch.save_baseline(vault)
    write(vault / "project" / "p" / "b.md.要約.md", "note")
    write(vault / "project" / "p" / ".index.md", "idx")
    assert sorted(watch.snapshot(vault)) == ["project/p/b.md"]
    assert watch.changed(vault) is False

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from vault_inbox import lock


def test_lock_second_acquire_refused(vault: Path):
    assert lock.acquire(vault, "organize") is True
    assert lock.acquire(vault, "watch") is False
    held = lock.holder(vault)
    assert held["owner"] == "organize"
    assert isinstance(held["pid"], int)


def test_lock_stale_is_taken_over(vault: Path):
    assert lock.acquire(vault, "organize") is True
    path = vault / ".vault-inbox" / "lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["time"] -= 4000
    path.write_text(json.dumps(data), encoding="utf-8")
    assert lock.acquire(vault, "watch") is True
    assert lock.holder(vault)["owner"] == "watch"


def test_organize_lock_survives_a_long_confirmation(vault: Path):
    """organize holds the lock while it waits for answers; 10 minutes is normal."""
    assert lock.acquire(vault, "organize") is True
    path = vault / ".vault-inbox" / "lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["time"] -= 1800
    path.write_text(json.dumps(data), encoding="utf-8")
    assert lock.acquire(vault, "watch") is False
    assert lock.holder(vault)["owner"] == "organize"


def test_old_holder_cannot_touch_or_release_the_new_holders_lock(vault: Path):
    assert lock.acquire(vault, "watch", 30.0) is True
    old_token = lock.holder(vault)["token"]
    _age_lock(vault, 31)
    assert lock.acquire(vault, "watch", 30.0) is True  # taken over by a second watch
    new = lock.holder(vault)
    assert new["token"] != old_token
    lock.touch(vault, "watch", token=old_token)
    lock.release(vault, "watch", token=old_token)
    assert lock.holder(vault) == new  # neither refreshed nor deleted
    lock.release(vault, "watch", token=new["token"])
    assert lock.holder(vault) is None


def test_release_only_by_owner(vault: Path):
    lock.acquire(vault, "organize")
    lock.release(vault, "watch")
    assert lock.holder(vault)["owner"] == "organize"
    lock.release(vault, "organize")
    assert lock.holder(vault) is None


def test_wait_for_free_returns_after_release(vault: Path):
    lock.acquire(vault, "organize")
    threading.Timer(0.1, lock.release, args=(vault, "organize")).start()
    assert lock.wait_for_free(vault, timeout=5.0) is True
    assert lock.holder(vault) is None


def test_wait_for_free_times_out(vault: Path):
    lock.acquire(vault, "organize")
    start = time.monotonic()
    assert lock.wait_for_free(vault, timeout=0.2) is False
    assert time.monotonic() - start < 2.0


def _age_lock(vault: Path, seconds: float) -> None:
    path = vault / ".vault-inbox" / "lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["time"] -= seconds
    path.write_text(json.dumps(data), encoding="utf-8")


def _race(vault: Path, owners: list[str], stale_after: float = 600.0) -> list[bool]:
    barrier = threading.Barrier(len(owners))
    results: dict[str, bool] = {}

    def run(owner: str) -> None:
        barrier.wait()
        results[owner] = lock.acquire(vault, owner, stale_after)

    threads = [threading.Thread(target=run, args=(o,)) for o in owners]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [results[o] for o in owners]


def test_concurrent_acquire_exactly_one_wins(vault: Path):
    for _ in range(20):
        (vault / ".vault-inbox" / "lock.json").unlink(missing_ok=True)
        assert _race(vault, [f"o{i}" for i in range(8)]).count(True) == 1


def test_concurrent_stale_takeover_exactly_one_wins(vault: Path):
    for _ in range(20):
        (vault / ".vault-inbox" / "lock.json").unlink(missing_ok=True)
        lock.acquire(vault, "organize")
        _age_lock(vault, 4000)
        assert _race(vault, ["watch", "ask-record"]).count(True) == 1


def test_fresh_empty_or_garbled_lock_is_held(vault: Path):
    path = vault / ".vault-inbox" / "lock.json"
    for text in ("", "{not json"):
        path.write_text(text, encoding="utf-8")
        assert lock.acquire(vault, "watch") is False
        assert path.read_text(encoding="utf-8") == text


def test_old_garbled_lock_is_taken_over(vault: Path):
    import os

    path = vault / ".vault-inbox" / "lock.json"
    path.write_text("", encoding="utf-8")
    os.utime(path, (time.time() - 4000, time.time() - 4000))
    assert lock.acquire(vault, "watch") is True


def test_acquire_without_vault_dir_returns_false(tmp_path: Path):
    assert lock.acquire(tmp_path, "organize") is False


def test_touch_never_exposes_empty_lock(vault: Path):
    lock.acquire(vault, "watch")
    path = vault / ".vault-inbox" / "lock.json"
    stop = threading.Event()

    def toucher() -> None:
        while not stop.is_set():
            lock.touch(vault, "watch")

    t = threading.Thread(target=toucher)
    t.start()
    bad = 0
    try:
        for _ in range(2000):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue  # transient Windows sharing violation, not an empty file
            try:
                assert json.loads(text)["owner"] == "watch"
            except ValueError:
                bad += 1
    finally:
        stop.set()
        t.join()
    assert bad == 0


def test_touch_by_other_owner_does_nothing(vault: Path):
    lock.acquire(vault, "organize")
    before = lock.holder(vault)
    lock.touch(vault, "watch")
    assert lock.holder(vault) == before


def test_watch_lock_untouched_past_window_is_taken_over(vault: Path):
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"
    spec = importlib.util.spec_from_file_location("vi_cli2", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    window = cli._watch_stale_after(5.0)
    assert 30.0 <= window < 600.0
    lock.acquire(vault, "watch", window)
    assert lock.acquire(vault, "watch", window) is False
    _age_lock(vault, window + 1)
    assert lock.acquire(vault, "watch", window) is True


def test_watch_command_leaves_a_new_holders_lock_alone(vault: Path, monkeypatch):
    """A watch that was taken over must not refresh or delete the new holder's lock."""
    import argparse
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"
    spec = importlib.util.spec_from_file_location("vi_cli_watch_token", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    newcomer: dict = {}

    def poll(root, interval, settle, heartbeat):
        _age_lock(vault, 31)  # past the 30 s window of an idle watch
        assert lock.acquire(vault, "watch", 30.0) is True  # a second watch takes over
        newcomer.update(lock.holder(vault))
        heartbeat()  # the first watch's heartbeat must not refresh it
        return iter(())

    monkeypatch.setattr(cli.watching, "poll", poll)
    cli._cmd_watch(argparse.Namespace(root=str(vault), interval=0.01, settle=0.01))
    assert lock.holder(vault) == newcomer  # not refreshed, and not released at exit


def test_session_and_pass_locks_are_independent(vault: Path):
    assert lock.acquire(vault, "watch") is True
    assert lock.acquire(vault, "ask-record", name="pass") is True
    assert (vault / ".vault-inbox" / "pass.json").is_file()
    assert lock.acquire(vault, "organize", name="pass") is False
    assert lock.holder(vault, name="pass")["owner"] == "ask-record"
    assert lock.holder(vault)["owner"] == "watch"
    lock.release(vault, "ask-record", name="pass")
    assert lock.holder(vault, name="pass") is None
    assert lock.holder(vault)["owner"] == "watch"
    lock.release(vault, "watch", name="pass")  # other name: no effect
    assert lock.holder(vault)["owner"] == "watch"


def _cli_main():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"
    spec = importlib.util.spec_from_file_location("vi_cli_lock", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli.main


def _cli(vault: Path, capsys, *args: str) -> dict:
    assert _cli_main()([args[0], "--root", str(vault), *args[1:]]) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_ask_record_waits_for_running_pass(vault: Path, capsys):
    assert _cli(vault, capsys, "lock", "--owner", "watch")["acquired"] is True
    assert _cli(vault, capsys, "lock", "--name", "pass", "--owner", "watch") == {
        "acquired": True,
        "holder": None,
    }
    refused = _cli(vault, capsys, "lock", "--name", "pass", "--owner", "ask-record")
    assert refused["acquired"] is False
    assert refused["holder"]["owner"] == "watch"
    _cli(vault, capsys, "unlock", "--name", "pass", "--owner", "watch")
    took = _cli(vault, capsys, "lock", "--name", "pass", "--owner", "ask-record")
    assert took["acquired"] is True
    assert lock.holder(vault)["owner"] == "watch"  # session untouched


def test_cli_ask_record_acquires_while_watch_session_idle(vault: Path, capsys):
    assert _cli(vault, capsys, "lock", "--owner", "watch")["acquired"] is True
    took = _cli(vault, capsys, "lock", "--name", "pass", "--owner", "ask-record")
    assert took["acquired"] is True
    assert _cli(vault, capsys, "lock", "--owner", "organize")["acquired"] is False


def test_lock_stores_holders_own_window(vault: Path):
    lock.acquire(vault, "watch", 30.0)
    assert lock.holder(vault)["stale_after"] == 30.0


def test_stale_watch_lock_is_taken_over_by_organize(vault: Path):
    assert lock.acquire(vault, "watch", 30.0) is True
    _age_lock(vault, 31)
    assert lock.acquire(vault, "organize") is True
    assert lock.holder(vault)["owner"] == "organize"


def test_live_organize_lock_is_not_taken_by_later_watch(vault: Path):
    assert lock.acquire(vault, "organize") is True
    _age_lock(vault, 31)
    assert lock.acquire(vault, "watch", 30.0) is False
    assert lock.holder(vault)["owner"] == "organize"


def test_lock_without_stored_window_falls_back_to_one_hour(vault: Path):
    path = vault / ".vault-inbox" / "lock.json"
    old = {"owner": "organize", "pid": 1, "token": "t"}
    path.write_text(json.dumps({**old, "time": time.time() - 3500}), encoding="utf-8")
    assert lock.acquire(vault, "watch", 30.0) is False
    path.write_text(json.dumps({**old, "time": time.time() - 3601}), encoding="utf-8")
    assert lock.acquire(vault, "watch", 30.0) is True

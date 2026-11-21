from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from pathlib import Path

OWNERS = ("organize", "watch", "ask-record")
# organize holds the lock while it waits for the user's answers, with no heartbeat,
# so the default window must outlast a long confirmation. watch sets its own, short one.
DEFAULT_STALE_AFTER = 3600.0
# "session": an organize or watch session is alive.
# "pass": an organize pass or an ask relation write is running right now.
NAMES = {"session": "lock.json", "pass": "pass.json"}


def _path(root: Path, name: str = "session") -> Path:
    return root / ".vault-inbox" / NAMES[name]


def holder(root: Path, name: str = "session") -> dict | None:
    try:
        data = json.loads(_path(root, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _window(data: object) -> float:
    """The holder's own stale_after, stored in the lock when it was acquired."""
    value = data.get("stale_after") if isinstance(data, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return DEFAULT_STALE_AFTER


def _state(root: Path, name: str) -> str:
    """ "free", "held" or "stale", judged by the holder's own window.

    An unreadable lock is held until its mtime is older than the default window.
    """
    path = _path(root, name)
    held = holder(root, name)
    if held is not None and isinstance(held.get("time"), (int, float)):
        written = held["time"]
    else:
        try:
            written = path.stat().st_mtime
        except OSError:
            return "free"
    return "stale" if time.time() - written > _window(held) else "held"


def _publish(root: Path, owner: str, token: str, name: str, stale_after: float) -> bool:
    """Create the lock with its content in one step.

    The content is a finished temp file, hard-linked into place.
    """
    path = _path(root, name)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{token}")
    tmp.write_text(
        json.dumps(
            {
                "owner": owner,
                "pid": os.getpid(),
                "time": time.time(),
                "token": token,
                "stale_after": stale_after,
            }
        ),
        encoding="utf-8",
    )
    try:
        os.link(tmp, path)
    except FileExistsError:
        return False
    finally:
        tmp.unlink(missing_ok=True)
    return True


def _mine(root: Path, token: str, name: str) -> bool:
    for _ in range(
        10
    ):  # the file may be briefly absent while a racing taker restores it
        held = holder(root, name)
        if held is not None:
            return held.get("token") == token
        time.sleep(0.01)
    return False


def acquire(
    root: Path,
    owner: str,
    stale_after: float = DEFAULT_STALE_AFTER,
    name: str = "session",
) -> bool:
    """Take the lock. stale_after is stored as this holder's own window: others
    may take the lock over only after it has gone untouched for that long."""
    path = _path(root, name)
    if not path.parent.is_dir():
        return False
    token = secrets.token_hex(8)
    for _ in range(3):
        if _publish(root, owner, token, name, stale_after):
            return _mine(root, token, name)
        if _state(root, name) == "held":
            return False
        # Stale: move it aside under a unique name, so only one taker removes it.
        aside = path.with_name(f"{path.name}.stale-{os.getpid()}-{token}")
        try:
            path.replace(aside)
        except OSError:
            continue  # someone else already moved it; retry the normal create
        try:
            data = json.loads(aside.read_text(encoding="utf-8"))
            fresh = time.time() - data["time"] <= _window(data)
        except (OSError, ValueError, KeyError, TypeError):
            fresh = False
        if fresh:  # we moved a lock another taker had just created: put it back
            with contextlib.suppress(OSError):
                os.link(aside, path)
            aside.unlink(missing_ok=True)
            return False
        aside.unlink(missing_ok=True)
    return False


def _is_holder(held: dict | None, owner: str, token: str | None) -> bool:
    """Same owner, and, when given, the same token (a taken-over holder differs)."""
    if not held or held.get("owner") != owner:
        return False
    return token is None or held.get("token") == token


def touch(
    root: Path, owner: str, name: str = "session", token: str | None = None
) -> None:
    """Refresh the lock's time so a long-running owner is not taken as stale."""
    held = holder(root, name)
    if not _is_holder(held, owner, token):
        return
    held["time"] = time.time()
    path = _path(root, name)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        tmp.write_text(json.dumps(held), encoding="utf-8")
        for attempt in range(2):
            try:
                Path(tmp).replace(path)
                return
            except PermissionError:  # transient on Windows while a reader has it open
                if attempt == 0:
                    time.sleep(0.02)
    except OSError:
        pass
    tmp.unlink(missing_ok=True)


def release(
    root: Path, owner: str, name: str = "session", token: str | None = None
) -> None:
    if _is_holder(holder(root, name), owner, token):
        _path(root, name).unlink(missing_ok=True)


def wait_for_free(root: Path, timeout: float = 60.0, name: str = "session") -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if _state(root, name) != "held":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)

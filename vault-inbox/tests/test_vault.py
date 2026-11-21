from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from vault_inbox.vault import has_obsidian, init_layout, is_initialized

CLI = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"


def test_init_layout_creates_dirs(tmp_path):
    created = init_layout(tmp_path)
    names = {"inbox", "project", "shared", ".vault-inbox", ".vault-inbox/text"}
    assert set(created) == names
    for n in names:
        assert (tmp_path / n).is_dir()


def test_init_layout_keeps_existing(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "a.md").write_text("x", encoding="utf-8")
    first = init_layout(tmp_path)
    assert "inbox" not in first
    assert (tmp_path / "inbox" / "a.md").read_text(encoding="utf-8") == "x"
    assert init_layout(tmp_path) == []


def test_is_initialized_needs_both(tmp_path):
    (tmp_path / "inbox").mkdir()
    assert not is_initialized(tmp_path)
    (tmp_path / ".vault-inbox").mkdir()
    assert is_initialized(tmp_path)


def test_has_obsidian(tmp_path):
    assert not has_obsidian(tmp_path)
    (tmp_path / ".obsidian").mkdir()
    assert has_obsidian(tmp_path)


def test_cli_status_json(tmp_path):
    def run(*args):
        r = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), *args, "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(r.stdout)

    assert run("status") == {
        "initialized": False,
        "has_obsidian": False,
        "missing_deps": [],
    }
    out = run("init")
    assert "inbox" in out["created"]
    assert out["has_obsidian"] is False
    assert run("status")["initialized"] is True

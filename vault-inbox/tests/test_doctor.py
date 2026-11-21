from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from vault_inbox import doctor

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"
MARKS = ("[OK]", "[NG]", "[任意]", "[情報]")


def _snapshot(root: Path) -> list[str]:
    return sorted(str(p) for p in root.rglob("*"))


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _register(home: Path, plugin_root: Path) -> Path:
    mp = home / "mp"
    (mp / ".claude-plugin").mkdir(parents=True)
    (mp / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "vault-inbox", "source": "./vault-inbox"}]}),
        encoding="utf-8",
    )
    known = home / "known.json"
    known.write_text(
        json.dumps(
            {
                "mine": {
                    "source": {"source": "github", "repo": "o/r"},
                    "installLocation": str(mp),
                }
            }
        ),
        encoding="utf-8",
    )
    return known


def test_output_lines_use_marks_and_hints(tmp_path):
    text, code = doctor.run(tmp_path / "data", known=tmp_path / "none.json")
    assert code in (0, 3)
    lines = _lines(text)
    assert lines[0].startswith(("[OK] 実行環境:", "[NG] 実行環境:"))
    assert lines[1].startswith(("[OK] 保存先:", "[NG] 保存先:"))
    assert lines[-1].startswith("[情報] プラグインのバージョン: v")
    for ln in lines:
        assert ln.startswith(MARKS) or ln.startswith("  → "), ln


def test_doctor_cli_changes_nothing_and_exits_zero(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    before = _snapshot(tmp_path)
    env = {"USERPROFILE": str(home), "HOME": str(home), "PYTHONUTF8": "1"}
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "doctor", "--data", str(data)],
        capture_output=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout
    assert "（GitHub のマーケットプレイスに登録していないため" in r.stdout
    assert _snapshot(tmp_path) == before


def test_unwritable_data_is_ng_with_exit_3(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "_writable", lambda _p: False)
    text, code = doctor.run(tmp_path / "data", known=tmp_path / "none.json")
    assert code == 3
    lines = _lines(text)
    i = next(i for i, ln in enumerate(lines) if ln.startswith("[NG] 保存先"))
    assert lines[i + 1].startswith("  → ")


def test_missing_library_is_optional_not_ng(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.extract, "missing_dependencies", lambda: ["pypdf"])
    text, code = doctor.run(tmp_path, known=tmp_path / "none.json")
    assert "[任意] pypdf:" in text
    assert "[OK] python-docx:" in text
    assert code == 0
    line = next(ln for ln in _lines(text) if "pypdf:" in ln)
    assert not line.startswith("[NG]")


def test_fts5_unavailable_is_ng(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise doctor.sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(doctor.sqlite3, "connect", boom)
    text, code = doctor.run(tmp_path, known=tmp_path / "none.json")
    assert "[NG] SQLite FTS5 trigram:" in text
    assert code == 3


def test_latest_check_states(tmp_path):
    known = _register(tmp_path, doctor.PLUGIN_ROOT)
    current = json.loads(
        (doctor.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8")
    )["version"]
    urls = []

    def same(url):
        urls.append(url)
        return json.dumps({"version": current})

    ok = doctor._check_version(known, same)
    assert ok == [f"[情報] プラグインのバージョン: v{current}（最新です）"]
    assert urls == [
        "https://raw.githubusercontent.com/o/r/HEAD/vault-inbox/.claude-plugin/plugin.json"
    ]

    new = doctor._check_version(known, lambda _u: json.dumps({"version": "99.0.0"}))
    assert "（GitHub に v99.0.0 があります）" in new[0]
    assert new[1:] == [
        "  → /plugin marketplace update mine を実行する",
        "  → /plugin update vault-inbox@mine を実行する",
        "  → Claude Code を開き直す",
    ]


def test_latest_unavailable_is_not_ng(tmp_path):
    known = _register(tmp_path, doctor.PLUGIN_ROOT)

    def offline(_url):
        raise OSError("offline")

    out = doctor._check_version(known, offline)
    assert "（最新のバージョンを確認できませんでした: offline）" in out[0]
    assert out[1].startswith("  → ネットワークにつながっているか")
    assert not out[0].startswith("[NG]")


def test_marketplace_entry_without_repo_is_skipped(tmp_path):
    known = _register(tmp_path, doctor.PLUGIN_ROOT)
    data = json.loads(known.read_text(encoding="utf-8"))
    del data["mine"]["source"]["repo"]
    known.write_text(json.dumps(data), encoding="utf-8")
    out = doctor._check_version(known, lambda _u: "{}")
    assert len(out) == 1
    assert out[0].startswith("[情報] プラグインのバージョン: v")
    assert "登録していないため" in out[0]

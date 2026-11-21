"""`doctor`: report whether the dependencies are met. Changes nothing."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

from . import extract

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "vault-inbox"
MIN_PYTHON = (3, 10)
FETCH_TIMEOUT = 5.0


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:  # noqa: S310
        return r.read().decode("utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _check_python() -> list[str]:
    v = sys.version_info
    text = f"Python {v.major}.{v.minor}.{v.micro}（3.10 以上が必要）"
    if (v.major, v.minor) >= MIN_PYTHON:
        return [f"[OK] 実行環境: {text}"]
    return [
        f"[NG] 実行環境: {text}",
        "  → Python 3.10 以上を入れ、python コマンドで起動できるようにする",
    ]


def _writable(data: Path) -> bool:
    probe = data
    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK)


def _check_data(data: Path) -> list[str]:
    if _writable(data):
        note = "" if data.exists() else "（まだありません。作成できます）"
        return [f"[OK] 保存先: {data} に書き込めます{note}"]
    return [
        f"[NG] 保存先: {data} に書き込めません",
        "  → フォルダの書き込み権限を確認する",
    ]


def _check_libraries() -> list[str]:
    missing = set(extract.missing_dependencies())
    root = PLUGIN_ROOT / "requirements.txt"
    out: list[str] = []
    for pip in extract._DEPENDENCIES.values():  # noqa: SLF001
        if pip in missing:
            out.append(f"[任意] {pip}: 入っていません（対応する形式を読むときに必要）")
            out.append(f'  → python -m pip install -r "{root}" を実行する')
        else:
            out.append(f"[OK] {pip}: 入っています")
    return out


def _check_fts5() -> list[str]:
    ver = sqlite3.sqlite_version
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(b, tokenize='trigram')")
        finally:
            con.close()
    except sqlite3.Error:
        return [
            f"[NG] SQLite FTS5 trigram: 使えません（SQLite {ver}）",
            "  → SQLite 3.34 以上と FTS5 を含む Python に入れ替える",
        ]
    return [f"[OK] SQLite FTS5 trigram: 使えます（SQLite {ver}）"]


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def _github_source(known: Path) -> tuple[str, str, str] | None:
    """(marketplace name, repo, plugin.json path in the repo) for this plugin."""
    data = _read_json(known)
    for mp_name, entry in data.items():
        src = entry.get("source", {})
        if src.get("source") != "github":
            continue
        try:
            listing = _read_json(
                Path(entry["installLocation"]) / ".claude-plugin" / "marketplace.json"
            )
        except (OSError, ValueError, KeyError):
            continue
        for p in listing.get("plugins", []):
            if p.get("name") == PLUGIN_NAME:
                base = str(p.get("source", ".")).removeprefix("./").strip("/")
                path = ".claude-plugin/plugin.json"
                if base not in ("", "."):
                    path = f"{base}/{path}"
                return mp_name, src["repo"], path
    return None


def _check_version(known: Path, fetch=_fetch_text) -> list[str]:
    current = _read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")["version"]
    head = f"[情報] プラグインのバージョン: v{current}"
    try:
        found = _github_source(known)
    except (OSError, ValueError, AttributeError):
        found = None
    if found is None:
        return [
            head + "（GitHub のマーケットプレイスに登録していないため、"
            "最新かは確認しません）"
        ]
    mp_name, repo, path = found
    url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
    try:
        latest = json.loads(fetch(url))["version"]
        newer = _version_tuple(latest) > _version_tuple(current)
    except Exception as e:  # noqa: BLE001 - any failure only downgrades the report
        reason = str(e) or type(e).__name__
        return [
            head + f"（最新のバージョンを確認できませんでした: {reason}）",
            "  → ネットワークにつながっているか、github.com への通信を止めていないかを"
            "確認する",
        ]
    if not newer:
        return [head + "（最新です）"]
    return [
        head + f"（GitHub に v{latest} があります）",
        f"  → /plugin marketplace update {mp_name} を実行する",
        f"  → /plugin update {PLUGIN_NAME}@{mp_name} を実行する",
        "  → Claude Code を開き直す",
    ]


def run(data: Path, known: Path | None = None, fetch=_fetch_text) -> tuple[str, int]:
    """Return (output text, exit code)."""
    if known is None:
        known = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"
    lines = [
        *_check_python(),
        *_check_data(data),
        *_check_libraries(),
        *_check_fts5(),
        *_check_version(known, fetch),
    ]
    code = 3 if any(ln.startswith("[NG]") for ln in lines) else 0
    return "\n".join(lines) + "\n", code

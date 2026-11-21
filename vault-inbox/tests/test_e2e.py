"""End-to-end checks: drive the CLI by subprocess against a temp Vault.

Claude's judgment is simulated by passing explicit `place` arguments.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import docx

CLI = Path(__file__).resolve().parent.parent / "scripts" / "vault_inbox.py"


def run(vault: Path, *args: str) -> dict:
    p = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(CLI),
            args[0],
            "--root",
            str(vault),
            *args[1:],
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(p.stdout)


def make_inbox(vault: Path) -> None:
    inbox = vault / "inbox"
    (inbox / "契約書.md").write_text(
        "# 業務委託契約\n契約の期間は一年とする。", encoding="utf-8"
    )
    (inbox / "メモ.txt").write_text(
        "打合せメモ。来週の予定を確認する。", encoding="utf-8"
    )
    (inbox / "仕様.html").write_text(
        "<html><body><p>画面の仕様について</p></body></html>", encoding="utf-8"
    )
    d = docx.Document()
    d.add_paragraph("見積の内訳と契約金額")
    d.save(str(inbox / "見積.docx"))


def place_all(vault: Path, items: list[dict], dests: dict[str, str]) -> dict[str, dict]:
    placed = {}
    for it in items:
        assert it["status"] == "ready", it
        r = run(
            vault,
            "place",
            "--name",
            it["name"],
            "--dest",
            dests[it["name"]],
            "--id",
            it["id"],
            "--hash",
            it["hash"],
            "--date",
            "2026-11-21",
            "--summary",
            f"要約 {it['name']}",
        )
        placed[it["name"]] = r["doc"]
    return placed


def test_e2e_init_intake_place_search_relate_ask(tmp_path):
    run(tmp_path, "init")
    make_inbox(tmp_path)
    items = run(tmp_path, "intake")["items"]
    assert {i["status"] for i in items} == {"ready"}
    assert len(items) == 4

    dests = {
        "契約書.md": "project/案件A",
        "見積.docx": "project/案件A",
        "メモ.txt": "shared/議事",
        "仕様.html": "shared/議事",
    }
    placed = place_all(tmp_path, items, dests)
    assert (tmp_path / "project/案件A/契約書.md").is_file()
    assert (tmp_path / "shared/議事/仕様.html").is_file()
    assert list((tmp_path / "inbox").iterdir()) == []

    run(tmp_path, "indexmd")
    assert (tmp_path / "project/案件A/見積.docx.要約.md").is_file()
    assert not list(tmp_path.rglob("*index.md"))  # no folder index any more

    hits = run(tmp_path, "search", "--query", "契約")
    paths = {d["path"] for d in hits["docs"]}
    assert "project/案件A/契約書.md" in paths
    assert "project/案件A/見積.docx" in paths

    a, b = placed["契約書.md"]["id"], placed["メモ.txt"]["id"]
    assert run(tmp_path, "relate", "--src", a, "--dst", b, "--kind", "related") == {
        "ok": True
    }
    ex = run(tmp_path, "expand", "--ids", a)
    assert b in ex["materials"]
    assert "shared/議事/メモ.txt" in {d["path"] for d in ex["docs"]}

    run(tmp_path, "indexmd")
    # the Markdown material carries its own properties; the txt gets a summary note
    md = (tmp_path / "project/案件A/契約書.md").read_text(encoding="utf-8")
    assert md.startswith("---\n") or md.startswith("---\r\n")
    assert "[[shared/議事/メモ.txt.要約.md|related → メモ.txt]]" in md
    note = (tmp_path / "shared/議事/メモ.txt.要約.md").read_text(encoding="utf-8")
    assert "[[project/案件A/契約書.md|related ← 契約書.md]]" in note
    # rewriting our own properties is not an edit: scan sees nothing new
    scan = run(tmp_path, "scan")
    assert scan["updated"] == []
    assert scan["unresolved"] == []


def test_e2e_user_moves_and_edits_then_scan(tmp_path):
    run(tmp_path, "init")
    make_inbox(tmp_path)
    items = run(tmp_path, "intake")["items"]
    dests = {
        n: "project/案件A" for n in ("契約書.md", "メモ.txt", "仕様.html", "見積.docx")
    }
    placed = place_all(tmp_path, items, dests)
    a, b = placed["契約書.md"]["id"], placed["メモ.txt"]["id"]
    run(tmp_path, "relate", "--src", a, "--dst", b, "--kind", "related")
    run(tmp_path, "indexmd")
    assert run(tmp_path, "scan")["unresolved"] == []

    (tmp_path / "project/案件B").mkdir()
    shutil.move(
        str(tmp_path / "project/案件A/契約書.md"),
        str(tmp_path / "project/案件B/契約書.md"),
    )
    (tmp_path / "project/案件A/メモ.txt").write_text(
        "改訂した内容 ゼータ", encoding="utf-8"
    )

    r = run(tmp_path, "scan")
    assert r["moved"] == [
        {"id": a, "from": "project/案件A/契約書.md", "to": "project/案件B/契約書.md"}
    ]
    assert r["updated"] == [{"id": b, "path": "project/案件A/メモ.txt"}]
    assert r["unresolved"] == []

    assert run(tmp_path, "search", "--query", "ゼータ")["ids"] == [b]
    ex = run(tmp_path, "expand", "--ids", a)
    assert b in ex["materials"]  # relation and ids preserved

    run(tmp_path, "indexmd")
    note = (tmp_path / "project/案件A/メモ.txt.要約.md").read_text(encoding="utf-8")
    assert "project/案件B/契約書.md" in note  # the link follows the moved material
    assert "project/案件A/契約書.md" not in note


def test_e2e_uninitialized_vault_reports_status(tmp_path):
    r = run(tmp_path, "status")
    assert r["initialized"] is False
    run(tmp_path, "init")
    assert run(tmp_path, "status")["initialized"] is True


def test_e2e_rebuild_matches_after_deleting_index(tmp_path):
    run(tmp_path, "init")
    make_inbox(tmp_path)
    items = run(tmp_path, "intake")["items"]
    place_all(tmp_path, items, {i["name"]: "project/案件A" for i in items})
    before = run(tmp_path, "search", "--query", "契約")["ids"]
    assert before

    shutil.rmtree(tmp_path / ".vault-inbox/text")
    (tmp_path / ".vault-inbox/index.db").unlink()
    run(tmp_path, "rebuild")
    assert run(tmp_path, "search", "--query", "契約")["ids"] == before

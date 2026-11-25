"""organize・ask の動作解説ページ（page.html）を生成する。

使い方: python docs/organize-ask/build.py [--out <出力フォルダ>]

- 全文・大きさ・版・行番号は、実行のたびにリポジトリから読む。
- 標準出力は、実行のたびに、一時フォルダのデモ Vault でスクリプトを実行して採取する。
- 出力（page.html と、ブラウザで開く用の page.local.html）は、リポジトリの外に作る。
"""

from __future__ import annotations

import argparse
import ast
import functools
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PLUGIN = REPO / "vault-inbox"
SCRIPT = PLUGIN / "scripts" / "vault_inbox.py"
TEMPLATE = HERE / "page.html"

# ---- デモの入力（この解説のために書いた最小の例。リポジトリの写しではない） ----
MINUTES_NAME = "キックオフ議事録.md"
MINUTES = (
    "# キックオフ会議\n\n日時: 2026-11-10\n"
    "決定事項: 見積もりは 12 月 5 日までに確定する。\n担当は佐藤。\n"
)
MINUTES_EDIT = "追記: 見積もりの金額は 350 万円以内に収める。\n"
MINUTES_V2 = (
    "# キックオフ会議（第 2 回）\n\n日時: 2026-11-20\n"
    "決定事項: 納期を 2 月末に延ばす。\n"
)
QUOTE_NAME = "見積メモ.txt"
QUOTE = (
    "見積もり（案件A）\n作成日: 2026-11-12\n"
    "開発費 300 万円、保守費 月 5 万円。\n12 月 5 日に確定する予定。\n"
)
COPY_NAME = "見積メモのコピー.txt"
OLD_NAME = "旧仕様.doc"
MINUTES_DEST = "project/案件A/議事録"
QUOTE_DEST = "project/案件A/見積"
MEETING_DEST = "project/案件A/会議"  # 議事録を手で動かした先
QUOTE_MOVED_DEST = "project/案件A/見積書"  # 見積メモを手で動かした先
RELATION_KIND = "derived_from"
# page.html の例に埋める値（{{v:名前}}）。例の中の名前・パスを、手で写さないため
VALUES = {
    "minutes_name": MINUTES_NAME,
    "quote_name": QUOTE_NAME,
    "minutes_dest": MINUTES_DEST,
    "meeting_dest": MEETING_DEST,
    "relation_kind": RELATION_KIND,
}


# ---- リポジトリを読む ----
def rel_path(rel: str) -> Path:
    path = (REPO / rel).resolve()
    if REPO not in path.parents:
        raise SystemExit(f"リポジトリの外は読めない: {rel}")
    return path


def read(rel: str) -> str:
    return rel_path(rel).read_text(encoding="utf-8")


@functools.cache
def _tree(rel: str) -> ast.Module:
    return ast.parse(read(rel))


def func_line(rel: str, name: str) -> int:
    """関数（またはクラス）の定義行を、構文解析で求める。"""
    for node in ast.walk(_tree(rel)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node.lineno
    raise KeyError(f"{rel}: {name}")


def const(rel: str, name: str):
    """モジュール直下の定数 NAME = <リテラル> の値を求める。"""
    for node in _tree(rel).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise KeyError(f"{rel}: {name}")


def default_arg(rel: str, func: str, arg: str):
    """関数の引数の既定値を求める。"""
    for node in ast.walk(_tree(rel)):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            names = [a.arg for a in node.args.args]
            defaults = node.args.defaults
            offset = len(names) - len(defaults)
            return ast.literal_eval(defaults[names.index(arg) - offset])
    raise KeyError(f"{rel}: {func}")


# ---- デモの実行 ----
@dataclass
class Run:
    shown: str
    code: int
    out: str
    err: str
    args: list | None


class Demo:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.vault = tmp / "vault"
        self.data = tmp / "data"
        self.home = tmp / "home"
        for p in (self.vault, self.data, self.home):
            p.mkdir()
        self.runs: dict[str, Run] = {}
        self.files: dict[str, str] = {}
        self.ids: dict[str, str] = {}
        # 環境変数は、必要最小限だけ渡す（トークン・ユーザー名を、出力に混ぜない）
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "TEMP": str(tmp),
            "TMP": str(tmp),
            "PYTHONUTF8": "1",
        }

    def run(self, key: str, cmd: str, *opts: str, args: list[str] | None = None):
        argv = [sys.executable, "-X", "utf8", str(SCRIPT), cmd, "--root=."]
        shown = f"python -X utf8 \"<P>/scripts/vault_inbox.py\" {cmd} --root='.'"
        for o in opts:
            name, _, val = o.partition("=")
            argv.append(o)
            shown += f" {name}='{val}'"
        if args is not None:
            argsfile = self.data / "args.txt"
            argsfile.write_text("\n".join(args) + "\n", encoding="utf-8", newline="\n")
            argv.append(f"@{argsfile}")
            shown += ' @"<D>/args.txt"'
        return self._exec(key, argv, shown, args)

    def doctor(self, key: str):
        argv = [
            sys.executable,
            "-X",
            "utf8",
            str(SCRIPT),
            "doctor",
            "--data",
            str(self.data),
        ]
        shown = 'python -X utf8 "<P>/scripts/vault_inbox.py" doctor --data "<D>"'
        return self._exec(key, argv, shown, None)

    def _exec(self, key, argv, shown, args):
        p = subprocess.run(  # noqa: S603 - 自分のスクリプトを、固定の引数で起動する
            argv,
            cwd=self.vault,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=60,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.runs[key] = Run(shown, p.returncode, p.stdout, p.stderr, args)
        return p

    def json(self, key: str) -> dict:
        return json.loads(self.runs[key].out)

    def snap(self, key: str, rel: str) -> None:
        self.files[key] = (self.vault / rel).read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> None:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")

    def move(self, src: str, dst: str) -> None:
        (self.vault / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.vault / src), str(self.vault / dst))


def _args(**kw: str) -> list[str]:
    return [f"--{k.replace('_', '-')}={v}" for k, v in kw.items()]


def scenario(d: Demo) -> None:
    """手順書の順に、実際にスクリプトを実行する。"""
    d.run("status_uninit", "status")
    d.run("init", "init")
    d.run("status_ok", "status")
    d.doctor("doctor")

    d.write(f"inbox/{MINUTES_NAME}", MINUTES)
    d.write(f"inbox/{QUOTE_NAME}", QUOTE)
    d.write(f"inbox/{COPY_NAME}", QUOTE)
    d.write(f"inbox/{OLD_NAME}", "dummy")
    (d.vault / "inbox" / "作業用").mkdir()

    # --- organize 手順1: 準備 ---
    d.run("lock_session", "lock", "--owner=organize")
    d.run("lock_session_again", "lock", "--owner=organize")
    d.run("lock_pass", "lock", "--name=pass", "--owner=organize")
    d.run("lock_pass_ask", "lock", "--name=pass", "--owner=ask-record")
    d.run("snapshot_save", "snapshot-save")
    # --- 手順2 ---
    d.run("rebuild", "rebuild")
    d.run("resume", "resume")
    # --- 手順3 ---
    d.run("scan_empty", "scan")
    # --- 手順4 ---
    d.run("intake1", "intake")
    items = {i["name"]: i for i in d.json("intake1")["items"]}
    minutes, quote = items[MINUTES_NAME], items[QUOTE_NAME]
    d.ids["議事録"], d.ids["見積メモ"] = minutes["id"], quote["id"]
    d.files["fulltext_minutes"] = (
        d.vault / ".vault-inbox" / "text" / f"{minutes['id']}.txt"
    ).read_text(encoding="utf-8")
    d.run(
        "args_root",
        "place",
        args=["--root=.", *_args(name=MINUTES_NAME)],
    )
    d.run(
        "place_bad",
        "place",
        args=_args(
            name=MINUTES_NAME,
            dest="inbox/案件A",
            id=minutes["id"],
            hash=minutes["hash"],
            date="2026-11-10",
            summary="x",
        ),
    )
    d.run(
        "place_minutes",
        "place",
        args=_args(
            name=MINUTES_NAME,
            dest=MINUTES_DEST,
            id=minutes["id"],
            hash=minutes["hash"],
            date="2026-11-10",
            summary="キックオフ会議の議事録。見積もりの確定期限を 12 月 5 日と決めた。",
        ),
    )
    d.run(
        "place_quote",
        "place",
        args=_args(
            name=QUOTE_NAME,
            dest=QUOTE_DEST,
            id=quote["id"],
            hash=quote["hash"],
            date="2026-11-12",
            summary="案件A の見積メモ。開発費 300 万円、保守費は月 5 万円。",
        ),
    )
    for key, name in (
        ("mark_copy", COPY_NAME),
        ("mark_old", OLD_NAME),
        ("mark_dir", "作業用"),
    ):
        it = items[name]
        d.run(
            key,
            "inbox-mark",
            args=_args(name=name, hash=it["hash"], status=it["status"]),
        )
    # --- 手順5 ---
    d.run("indexmd1", "indexmd")
    d.snap("md_after_organize", f"{MINUTES_DEST}/{MINUTES_NAME}")
    d.snap("note_after_organize", f"{QUOTE_DEST}/{QUOTE_NAME}.要約.md")
    d.run("snapshot_absorb", "snapshot-absorb")
    d.run("unlock_pass", "unlock", "--name=pass", "--owner=organize")
    d.run("unlock_session", "unlock", "--owner=organize")

    # --- ask ---
    d.run("ask_status", "status")
    d.run("ask_search_none", "search", args=["--query=存在しない語"])
    d.run("ask_search", "search", args=["--query=見積もり"])
    ids = ",".join(d.json("ask_search")["ids"])
    d.run("ask_expand", "expand", f"--ids={ids}")
    d.run("ask_kinds", "kinds")
    d.run(
        "ask_relate_bad",
        "relate",
        args=_args(src=quote["id"], dst=minutes["id"], kind="参考"),
    )
    d.run("ask_lock", "lock", "--name=pass", "--owner=ask-record")
    d.run(
        "ask_relate",
        "relate",
        args=_args(src=quote["id"], dst=minutes["id"], kind=RELATION_KIND),
    )
    d.run("ask_indexmd", "indexmd")
    d.snap("md_after_ask", f"{MINUTES_DEST}/{MINUTES_NAME}")
    d.run("ask_unlock", "unlock", "--name=pass", "--owner=ask-record")

    # --- 手作業のあとの organize（手順1・2 は実行1 と同じなので省く） ---
    minutes_path = d.vault / MINUTES_DEST / MINUTES_NAME
    with minutes_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(MINUTES_EDIT)
    d.run("scan_updated", "scan")
    d.run(
        "update_meta",
        "update-meta",
        args=_args(
            id=minutes["id"],
            date="2026-11-10",
            summary="キックオフ会議の議事録。見積もりの確定期限と、金額の上限を決めた。",
        ),
    )
    with minutes_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("担当を佐藤から鈴木に変える。\n")
    d.move(f"{MINUTES_DEST}/{MINUTES_NAME}", f"{MEETING_DEST}/{MINUTES_NAME}")
    d.move(f"{QUOTE_DEST}/{QUOTE_NAME}", f"{QUOTE_MOVED_DEST}/{QUOTE_NAME}")
    d.run("scan_moved", "scan")
    new_path = f"{MEETING_DEST}/{MINUTES_NAME}"
    d.run(
        "resolve_bad_path",
        "resolve",
        args=_args(
            action="register",
            path=f"inbox/{COPY_NAME}",
            date="2026-11-10",
            summary="x",
        ),
    )
    d.run(
        "resolve_register",
        "resolve",
        args=_args(
            action="register",
            path=new_path,
            date="2026-11-10",
            summary="キックオフ会議の議事録。確定期限、金額の上限、担当の変更を決めた。",
        ),
    )
    d.ids["議事録（登録し直し）"] = d.json("resolve_register")["id"]
    d.run("resolve_drop", "resolve", "--action=drop", f"--id={minutes['id']}")
    d.run("dangling", "dangling")
    rel = d.json("dangling")["relations"][0]
    d.run(
        "relation_remove",
        "relation-remove",
        args=_args(src=rel["src"], dst=rel["dst"], kind=rel["kind"]),
    )
    d.write(f"inbox/{MINUTES_NAME}", MINUTES_V2)
    d.run("intake2", "intake")
    again = {i["name"]: i for i in d.json("intake2")["items"]}[MINUTES_NAME]
    d.ids["議事録（第 2 回）"] = again["id"]
    d.run(
        "place_collision",
        "place",
        args=_args(
            name=MINUTES_NAME,
            dest=MEETING_DEST,
            id=again["id"],
            hash=again["hash"],
            date="2026-11-20",
            summary="第 2 回のキックオフ会議。",
        ),
    )
    d.run(
        "mark_collision",
        "inbox-mark",
        args=_args(
            name=MINUTES_NAME,
            hash=again["hash"],
            status="name_collision",
            id=again["id"],
        ),
    )
    d.run("indexmd2", "indexmd")
    d.snap("md_final", new_path)
    d.files["meta_final"] = (d.vault / ".vault-inbox" / "meta.json").read_text(
        encoding="utf-8"
    )


# ---- 採取した出力の整形（パス・ランダムな値を印に置き換える） ----
_HEX32 = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")


class Scrubber:
    def __init__(self, d: Demo):
        self.d = d
        self.unknown: dict[str, str] = {}
        t = d.tmp
        pairs = [
            (d.vault, "<起動フォルダ>"),
            (d.data, "<D>"),
            (PLUGIN, "<P>"),
            (d.home, "<HOME>"),
            (t, "<T>"),
        ]
        self.paths: list[tuple[str, str]] = []
        for p, mark in pairs:
            for form in (str(p), p.as_posix()):
                self.paths.append((form, mark))
                self.paths.append((form.replace("\\", "\\\\"), mark))

    def __call__(self, text: str) -> str:
        for form, mark in self.paths:
            text = text.replace(form, mark)
        for role, real in self.d.ids.items():
            text = text.replace(real, f"<{role}のid>")

        def other(m: re.Match) -> str:
            return self.unknown.setdefault(m[0], f"<id-{len(self.unknown) + 1}>")

        text = _HEX32.sub(other, text)
        text = re.sub(r'("pid": )\d+', r"\1<pid>", text)
        text = re.sub(r'("time": )[\d.]+', r"\1<時刻>", text)
        return re.sub(r'("token": )"[0-9a-f]+"', r"\1<token>", text)


# ---- HTML の部品 ----
def esc(text: str) -> str:
    return html.escape(text, quote=False)


def labeled(label: str, cls: str, body_html: str, note: str = "") -> str:
    n = f'<span class="note">{esc(note)}</span>' if note else ""
    return (
        f'<div class="blk {cls}"><div class="blk-h"><span class="chip">{label}</span>'
        f"{n}</div>{body_html}</div>"
    )


def pre(text: str) -> str:
    return f"<pre>{esc(text)}</pre>"


def render_run(run: Run, scrub: Scrubber) -> str:
    out = []
    if run.args is not None:
        text = "\n".join(run.args) + "\n"
        out.append(
            labeled("書く", "write", pre(scrub(text)), "<D>/args.txt（Write ツール）")
        )
    body = f"$ {run.shown}\n"
    if run.out:
        body += run.out if run.out.endswith("\n") else run.out + "\n"
    if run.err:
        body += "（標準エラー）\n" + run.err
    body += f"[終了コード {run.code}]"
    out.append(labeled("標準出力", "out", pre(scrub(body))))
    pair = " pair" if run.args is not None else ""
    return f'<div class="run{pair}">' + "".join(out) + "</div>"


def kb(rel: str) -> str:
    return f"{rel_path(rel).stat().st_size:,} バイト"


def file_block(rel: str, folded: bool = False) -> str:
    size = kb(rel)
    inner = pre(read(rel))
    head = f"{esc(rel)}（{size}・全文）"
    if folded:
        return labeled(
            "読む",
            "read",
            f"<details><summary>{head}</summary>{inner}</details>",
        )
    return labeled("読む", "read", inner, f"{rel}（{size}・全文）")


# ---- 順序図（登場者ごとの線） ----
ACTORS = {  # 記号: (線の x 座標, 見出し)
    "U": (90, "利用者"),
    "C": (290, "Claude"),
    "D": (490, "手順書"),
    "S": (690, "スクリプト"),
    "V": (870, "Vault のファイル"),
}
# (出発, 到着, 文言, 返りか)。返りは破線にする
SEQUENCES = {
    "organize": [
        ("U", "C", "/vault-inbox:organize を実行する", False),
        ("D", "C", "SKILL.md の本文が入る", True),
        ("C", "S", "status・lock・snapshot-save・rebuild・resume（手順1・2）", False),
        ("S", "V", "ロック・索引を書く", False),
        ("S", "C", "JSON 1 行", True),
        ("C", "D", "Read scan.md（手順3の直前）", False),
        ("D", "C", "手順書の全文", True),
        ("C", "S", "scan", False),
        ("S", "C", "JSON（moved・updated・unresolved など）", True),
        ("C", "U", "AskUserQuestion（組み直す・登録する・外す）", False),
        ("U", "C", "選んだ選択肢", True),
        ("C", "S", "resolve・update-meta @args", False),
        ("C", "D", "Read intake.md（手順4の直前）", False),
        ("D", "C", "手順書の全文", True),
        ("C", "S", "intake", False),
        ("S", "C", "JSON（items）", True),
        ("C", "V", "Read 全文（.vault-inbox/text/）", False),
        ("C", "U", "AskUserQuestion（新しい分類先）", False),
        ("U", "C", "承認・却下", True),
        ("C", "S", "place @args", False),
        ("S", "V", "原本を移す・meta.json を書く", False),
        ("C", "S", "indexmd・snapshot-absorb・unlock", False),
        ("S", "V", "プロパティ・要約ノートを書く", False),
        ("C", "U", "最終報告（残した資料と理由）", False),
    ],
    "ask": [
        ("U", "C", "質問する（/vault-inbox:ask か自動起動）", False),
        ("D", "C", "SKILL.md の本文が入る", True),
        ("C", "S", "status", False),
        ("C", "S", "search @args（質問から取ったキーワード）", False),
        ("S", "V", "全文検索の索引を引く（index.db）", False),
        ("S", "C", "ids・docs", True),
        ("C", "S", "expand", False),
        ("S", "C", "materials・conflicts", True),
        ("C", "V", "Grep・Read 全文", False),
        ("C", "U", "回答（根拠へのリンク付き。保存しない）", False),
        ("C", "S", "kinds", False),
        ("C", "U", "AskUserQuestion（関係の候補）", False),
        ("U", "C", "承認した候補", True),
        ("C", "S", "lock --name=pass", False),
        ("C", "S", "relate @args・indexmd", False),
        ("S", "V", "meta.json・プロパティ・要約ノートを書く", False),
        ("C", "S", "unlock --name=pass", False),
        ("C", "U", "記録した関係を知らせる", False),
    ],
}


def sequence_svg(name: str) -> str:
    msgs = SEQUENCES[name]
    step, top = 32, 96
    height = top + step * len(msgs) + 20
    parts = [
        f'<svg viewBox="0 0 960 {height}" role="img" aria-label="'
        + esc(f"{name} の 1 回のやり取りの順序図")
        + '"><defs><marker id="ah-'
        + name
        + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/>'
        "</marker></defs>"
    ]
    for x, label in ACTORS.values():
        parts.append(
            f'<rect x="{x - 80}" y="10" width="160" height="34" rx="4" class="actor"/>'
            f'<text x="{x}" y="32" text-anchor="middle" class="sa">{esc(label)}</text>'
            f'<line x1="{x}" y1="44" x2="{x}" y2="{height - 10}" class="life"/>'
        )
    for i, (a, b, text, back) in enumerate(msgs):
        y = top + step * i
        xa, xb = ACTORS[a][0], ACTORS[b][0]
        d = ' stroke-dasharray="6 4"' if back else ""
        end = xb - 3 if xb > xa else xb + 3
        parts.append(
            f'<line x1="{xa}" y1="{y}" x2="{end}" y2="{y}" stroke="currentColor"'
            f' stroke-width="1.5"{d} marker-end="url(#ah-{name})"/>'
            f'<text x="{min(xa, xb) + 8}" y="{y - 7}" class="sl">{esc(text)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _git(*args: str) -> str:
    p = subprocess.run(  # noqa: S603 - 固定の引数で git を呼ぶ
        ["git", "-C", str(REPO), *args],  # noqa: S607
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    return p.stdout.strip()


def commit() -> str:
    """HEAD の短縮ハッシュ。未コミットの変更があれば、そう添える。"""
    head = _git("rev-parse", "--short", "HEAD") or "不明"
    return head + ("（未コミットの変更あり）" if _git("status", "--porcelain") else "")


def example_final_report(d: Demo) -> str:
    """実行2 の最終報告の例。名前・理由・件数は、採取した出力から作る。"""
    left = [
        i
        for i in d.json("intake2")["items"]
        if i["status"] != "skipped" and i["name"] != "作業用"
    ]
    lines = ["inbox/ に残した資料:"]
    for i in left:
        why = i["status"]
        if why == "ready":
            why = "name_collision"  # place が返した理由（place_collision の出力）
        extra = f"（{i['reason']} と同じ中身）" if why == "duplicate" else ""
        lines.append(f"- {i['name']}: {why}{extra}")
    placed = 0 if "error" in d.json("place_collision") else 1
    moved = len(d.json("scan_moved")["moved"])
    updated = len(d.json("scan_updated")["updated"])
    lines.append(f"配置: {placed} 件 / scan: moved {moved} 件・updated {updated} 件")
    return "\n".join(lines)


def resolve(key: str, d: Demo, scrub: Scrubber) -> str:
    kind, _, arg = key.partition(":")
    if kind == "run":
        return render_run(d.runs[arg], scrub)
    if kind == "vfile":
        return labeled(
            "読む", "read", pre(scrub(d.files[arg])), "Vault に実際にできたファイル"
        )
    if kind == "file":
        return file_block(arg)
    if kind == "fold":
        return file_block(arg, folded=True)
    if kind == "v":
        return esc(VALUES[arg])
    if kind == "example":
        return esc({"final_report": example_final_report}[arg](d))
    if kind == "seq":
        return sequence_svg(arg)
    if kind == "size":
        return kb(arg)
    if kind == "lines":
        return str(len(read(arg).splitlines()))
    if kind == "ln":
        rel, _, name = arg.rpartition(":")
        return str(func_line(rel, name))
    if kind == "const":
        rel, _, name = arg.rpartition(":")
        return str(const(rel, name))
    if kind == "default":
        rel, func, name = arg.split(":")
        return str(default_arg(rel, func, name))
    if kind == "ver":
        return json.loads(read("vault-inbox/.claude-plugin/plugin.json"))["version"]
    if kind == "commit":
        return commit()
    if kind == "py":
        return sys.version.split()[0]
    raise KeyError(key)


def check_leaks(page: str, tmp: Path) -> None:
    """一時フォルダ・リポジトリのパス・ユーザー名・メール・トークンの形が残っていれば止める。"""
    words = [tmp.name, str(tmp), tmp.as_posix(), str(REPO), REPO.as_posix()]
    words += [Path.home().name]
    words += [os.environ.get(k, "") for k in ("USERNAME", "USER", "COMPUTERNAME")]
    low = page.casefold()
    for w in words:
        if len(w) >= 4 and w.casefold() in low:
            raise SystemExit(f"置き換え漏れ: {w!r}")
    secret = re.search(r"(gh[pousr]_|sk-|xox[bp]-)[A-Za-z0-9_-]{16,}", page)
    mail = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", page)
    if secret or mail:
        raise SystemExit(f"個人情報らしい文字列: {(secret or mail)[0]!r}")


def build(out_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="vi-demo-") as t:
        tmp = Path(t).resolve()
        d = Demo(tmp)
        scenario(d)
        scrub = Scrubber(d)
        text = TEMPLATE.read_text(encoding="utf-8")
        page = re.sub(
            r"\{\{([^{}]+)\}\}", lambda m: resolve(m[1].strip(), d, scrub), text
        )
        check_leaks(page, tmp)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "page.html").write_text(page, encoding="utf-8", newline="\n")
    local = (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, '
        'viewport-fit=cover">'
        "<style>:root{color-scheme:light}body{margin:0;font:14px system-ui}"
        "img{max-width:100%}[hidden]{display:none!important}</style></head><body>"
        + page
        + "</body></html>"
    )
    (out_dir / "page.local.html").write_text(local, encoding="utf-8", newline="\n")
    print(f"出力: {out_dir / 'page.html'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(tempfile.gettempdir()) / "vault-inbox-docs",
        help="出力フォルダ（リポジトリの外）",
    )
    args = ap.parse_args()
    out = args.out.resolve()
    if REPO in (out, *out.parents):
        raise SystemExit("出力先はリポジトリの外にする")
    build(out)


if __name__ == "__main__":
    main()

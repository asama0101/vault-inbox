# vault-inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Obsidian の Vault をルートに、`inbox/` に置いた資料を整理（`organize`・`watch`）し、格納した資料から回答（`ask`）して、承認された関係を記録する Claude Code プラグイン `vault-inbox` を作る。

**Architecture:** 形式的な処理は Python パッケージ `vault_inbox`（1 つの CLI `vault_inbox.py` にサブコマンドを持たせ、入出力は JSON）に、判断と対話（分類先・要約・関係の発見・AskUserQuestion）は 4 つの SKILL.md に置く。メタデータと関係は `.vault-inbox/meta.json`（作り直せない）、検索は `.vault-inbox/index.db`（SQLite FTS5 trigram）と `.vault-inbox/text/<id>.txt`（どちらも作り直せる）。

**Tech Stack:** Python 3.10 以上、標準ライブラリ（`sqlite3`・`json`・`hashlib`・`html.parser`）、PDF・Office の抽出だけ `pypdf`・`python-docx`・`openpyxl`・`python-pptx`、テストは `pytest`。

**Spec:** `docs/spec-grill/specs/2026-11-21-vault-inbox-plugin-design.md`（図: 同名の `.svg`）。受入条件の番号は、この SPEC の「受入条件」の番号を指す。

## Global Constraints

- プラグイン名 `vault-inbox`。コマンドは `/vault-inbox:init`・`:organize`・`:watch`・`:ask`（4 つの skill）。
- プラグインのルートは `<作業フォルダ>\vault-inbox\`。この作業フォルダは git リポジトリではないので、Task 1 の最初に `git init` する（作業フォルダのルートで行う）。
- Vault のルートは、コマンドを実行したカレントフォルダ。`init` だけ `.obsidian/` がなければ AskUserQuestion の選択肢（続行する・やめる）で確認する。`organize`・`watch`・`ask` は、`inbox/` と `.vault-inbox/` の少なくとも一方がなければ、何もせず `init` を案内する。
- フォルダ: `inbox/`（サブフォルダなし）、`project/<プロジェクト>/<分類>/…`、`shared/<種類>/<サブ>/…`、`.vault-inbox/`。深さは、`project/`・`shared/` を 1 階層として最大 5 階層。超える分は 5 階層目に置く。
- 原本は、分類先のフォルダに、名前も内容も変えずに置く。資料ごとのノートは作らない。
- 対象の拡張子は `.md`・`.txt`・`.html`・`.pdf`・`.docx`・`.xlsx`・`.pptx` だけ。`.doc`・`.xls`・`.ppt`・画像などは対象外。
- 区分（受領・作成・参照）と `source` は付けない。
- メタデータは `id`・`hash`・`path`（Vault ルートからの `/` 区切りのパス）・`date`・`tags`・`summary`。
- 関係は（`src`, `dst`, `kind`）。`kind` は固定の語彙 `derived_from`・`supersedes`・`supports`・`conflicts_with`・`related`。`supersedes` は `src` が新版、`dst` が旧版。語彙の追加は利用者の承認が要る。
- `ask` は、検索結果から関係を両方向に 1 つ先まで辿る。`supersedes` の旧版は、直接ヒットしても材料から外す。`conflicts_with` は回答で併記する。回答は保存しない。
- 検索は FTS5 trigram。3 文字未満の語は `text/` の全文を直接探す。複数の語は AND。
- すべての承認・確認は、AskUserQuestion の選択肢で聞く（入力を求めない）。
- 同じ内容（`hash` 一致）の資料と、同じ分類先に同名で内容が違う原本は、取り込まず `inbox/` に残して知らせる。取り込めない資料（抽出失敗・対象外）も `inbox/` に残す。
- `_index.md` は `project/`・`shared/` の各フォルダに自動生成し、追従・`watch`・取り込みの対象にしない。Obsidian が開ける形式（`.md`・`.pdf`・画像）は `[[リンク]]`、それ以外はファイル名のテキストで書く。
- `watch` は Claude Code のセッション内で Monitor により動かす。`organize`・`ask` 自身の書き込みには反応しない。`.obsidian/`・`.vault-inbox/` は監視しない。
- 文字コードは UTF-8。スクリプトは `python -X utf8` で実行する。

## Review Focus

1. 空ファイル（0 バイト）と、抽出しても空文字になる資料: 取り込まず `inbox/` に残し、理由を知らせる（クラッシュしない）。
2. 日本語・空白・全角を含むファイル名とパス: `meta.json` の `path` は `/` 区切りで保存され、移動・改名の検出と `[[リンク]]` が壊れない。
3. `meta.json` が書き込み途中で壊れた: `meta.json.bak` から読み込み、`.bak` もなければ明示的なエラーで止まる（空のメタデータで上書きしない）。
4. Office の一時ファイル（`~$*.docx`）、隠しファイル、`inbox/` 内のサブフォルダ: 資料として取り込まない（理由つきで残すか、無視する）。
5. 検索語に FTS5 の特殊文字（`"`・`*`・`(`・`-`）を含む問い: 例外にならず、リテラルとして検索される。

---

## File Structure

```
vault-inbox/
  .claude-plugin/plugin.json
  requirements.txt
  scripts/
    vault_inbox.py            # CLI の入口（引数の解析と JSON 出力だけ）
    vault_inbox/
      __init__.py
      vault.py                # ルート・レイアウト・定数
      meta.py                 # MetaStore（メタデータ・関係・語彙・無視リスト）
      extract.py              # テキスト抽出
      index.py                # FTS5 索引・検索
      place.py                # 深さの制限・配置・「配置中」の再開
      scan.py                 # 追従の検出
      relations.py            # 関係の追加・行き先なしの検出・展開
      indexmd.py              # _index.md の生成
      lock.py                 # 排他
      watch.py                # 変化の検知
  skills/
    init/SKILL.md
    organize/SKILL.md
    watch/SKILL.md
    ask/SKILL.md
  tests/
    conftest.py
    test_*.py
```

---

### Task 1: 骨組み・Vault のレイアウト・`init`

**Files:**
- Create: `vault-inbox/.claude-plugin/plugin.json`, `vault-inbox/requirements.txt`, `vault-inbox/scripts/vault_inbox.py`, `vault-inbox/scripts/vault_inbox/__init__.py`, `vault-inbox/scripts/vault_inbox/vault.py`
- Create: `vault-inbox/tests/conftest.py`, `vault-inbox/tests/test_vault.py`

**Interfaces:**
- Produces（`vault.py`）:
  - `DEPTH_LIMIT = 5`、`SUPPORTED_EXTS: frozenset[str]`
  - `find_root(cwd: Path) -> Path`（`cwd` をそのまま返す）
  - `has_obsidian(root: Path) -> bool`、`is_initialized(root: Path) -> bool`（`inbox/` と `.vault-inbox/` の両方がある）
  - `init_layout(root: Path) -> list[str]`（なかった `inbox`・`project`・`shared`・`.vault-inbox`・`.vault-inbox/text` を作り、作った名前を返す。あるものは触らない）
- Produces（CLI）: `python -X utf8 scripts/vault_inbox.py <cmd> [--root DIR] ...`。標準出力は JSON 1 つ。`init` は `{"created": [...], "has_obsidian": bool}`。`status` は `{"initialized": bool, "has_obsidian": bool}`。
- Produces（`conftest.py`）: fixture `vault(tmp_path) -> Path`（`init_layout` 済みの Vault）、`write(path: Path, text: str)` ヘルパ。

- [ ] **Step 1: Write the failing tests** in `tests/test_vault.py`: `test_init_layout_creates_dirs`（空フォルダで 5 つ作られ、戻り値に含まれる）、`test_init_layout_keeps_existing`（既存ファイルが残り、2 回目は `[]`）、`test_is_initialized_needs_both`（`inbox/` だけでは False）、`test_has_obsidian`、`test_cli_status_json`（`subprocess` で `status` を呼び JSON を読む）。
- [ ] **Step 2: Run** `cd vault-inbox && python -X utf8 -m pytest tests/test_vault.py -v`。Expected: FAIL（`ModuleNotFoundError`）。
- [ ] **Step 3: `git init`（作業フォルダのルート）し、上記の関数・CLI を実装する。** `plugin.json` は `name: vault-inbox`、`version: 0.1.0`、`skills` ディレクトリを指す。`requirements.txt` は `pypdf`・`python-docx`・`openpyxl`・`python-pptx`・`pytest`。CLI は `argparse` のサブコマンドで、後続タスクが `register(subparsers)` で足せる構造にする。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: scaffold vault-inbox and init layout"`

---

### Task 2: メタデータ保管庫 `MetaStore`

**Files:**
- Create: `scripts/vault_inbox/meta.py`、`tests/test_meta.py`

**Interfaces:**
- Consumes: Task 1 の `vault.find_root`・`init_layout`。
- Produces（`meta.py`）:
  - `@dataclass Doc: id: str; hash: str; path: str; date: str; tags: list[str]; summary: str; state: str = "active"`（`state` は `"active"` か `"placing"`）
  - `file_hash(path: Path) -> str`（SHA-256 の 16 進）、`new_id() -> str`（UUID4 の 16 進 32 文字）
  - `class MetaStore(root: Path)`: `load()`（`.vault-inbox/meta.json` を読む。壊れていれば `meta.json.bak`。どちらもなければファイルなしは空、壊れているだけなら `MetaCorrupt` を送出）、`save()`（一時ファイルに書き、直前の版を `meta.json.bak` に退避して、`os.replace` で原子的に置き換える）
  - `docs() -> list[Doc]`、`get(id) -> Doc | None`、`by_path(path) -> Doc | None`、`by_hash(hash) -> list[Doc]`、`put(doc: Doc)`、`remove(id)`（その `id` を含む関係も消す）
  - `ignore(path: str, hash: str)`、`is_ignored(path: str, hash: str) -> bool`、`notified_dup(path, hash) -> bool`、`mark_dup(path, hash)`（複製を知らせた記録）
  - `relations() -> list[dict]`（`{"src","dst","kind"}`）、`add_relation(src, dst, kind)`（重複は無視。`kind` が語彙になければ `ValueError`）、`remove_relation(src, dst, kind)`
  - `vocabulary() -> list[str]`（初期値は固定の 5 種）、`add_kind(kind: str)`
- `class MetaCorrupt(Exception)`

- [ ] **Step 1: Write the failing tests**: `test_save_load_roundtrip`、`test_save_keeps_bak_of_previous_version`、`test_load_falls_back_to_bak_when_main_corrupt`（Review Focus 3）、`test_load_raises_when_corrupt_and_no_bak`（`MetaCorrupt`）、`test_remove_deletes_relations`、`test_add_relation_rejects_unknown_kind`、`test_add_kind_then_relation_ok`、`test_ignore_is_keyed_by_path_and_hash`（hash が変わると無視が外れる）、`test_by_path_uses_posix_separators`（`"project/案件 X/資料.pdf"` を `put` して `by_path` で引ける。Review Focus 2）。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_meta.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。JSON は `ensure_ascii=False`、UTF-8。スキーマは `{"version":1,"docs":{id:{...}},"relations":[...],"vocabulary":[...],"ignored":[{"path","hash"}],"dups":[{"path","hash"}]}`。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add atomic metadata store"`

---

### Task 3: テキスト抽出

**Files:**
- Create: `scripts/vault_inbox/extract.py`、`tests/test_extract.py`

**Interfaces:**
- Produces（`extract.py`）:
  - `class ExtractError(Exception)`（`reason: str`）
  - `extract_text(path: Path) -> str`（拡張子で分岐。`.md`・`.txt` は UTF-8（失敗したら `cp932`）、`.html` は `html.parser` でタグを除いたテキスト、`.pdf` は `pypdf`、`.docx` は `python-docx`（段落と表）、`.xlsx` は `openpyxl`（`read_only`、全シートのセルを空白区切り）、`.pptx` は `python-pptx`（全スライドのテキストと表）。結果が空白だけなら `ExtractError("empty")`。対象外の拡張子は `ExtractError("unsupported")`。ライブラリがない・壊れている・パスワード付きは `ExtractError("extract_failed: <例外名>")`）
  - `is_candidate(path: Path) -> bool`（`~$` で始まる名前と `.` で始まる名前は False。Review Focus 4）

- [ ] **Step 1: Write the failing tests**: テスト内で `.docx`・`.xlsx`・`.pptx` を各ライブラリで生成し（`.pdf` は同梱の最小 PDF の bytes をテストに埋め込む）、`test_extract_each_format_contains_known_word`（形式ごとに既知の語が含まれる）、`test_extract_empty_file_raises_empty`（0 バイト。Review Focus 1）、`test_extract_whitespace_only_raises_empty`、`test_extract_unsupported_ext`（`.doc`・`.png`）、`test_extract_corrupt_pdf_raises_extract_failed`、`test_extract_cp932_text`、`test_is_candidate_skips_office_temp_and_hidden`。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_extract.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。ライブラリの `import` は、使う関数の中で行い、未導入でも他の形式は動かす。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS（`pip install -r requirements.txt` 済み）。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add text extraction for supported formats"`

---

### Task 4: 全文検索の索引

**Files:**
- Create: `scripts/vault_inbox/index.py`、`tests/test_index.py`

**Interfaces:**
- Consumes: Task 2 の `MetaStore`。全文は `.vault-inbox/text/<id>.txt`。
- Produces（`index.py`）:
  - `save_text(root: Path, doc_id: str, text: str) -> Path`、`load_text(root, doc_id) -> str`
  - `rebuild(root: Path, store: MetaStore) -> int`（`active` の資料だけで `.vault-inbox/index.db` を作り直す。全文がない資料は、`store` の `path` の原本から `extract_text` して `save_text` で補う。登録件数を返す）
  - `ensure(root, store) -> bool`（`index.db` が無い・開けない場合に `rebuild` して True。そうでなければ False）
  - `search(root: Path, store: MetaStore, query: str, limit: int = 20) -> list[str]`（`doc_id` のリスト。語は空白で分け、すべてを含む資料（AND）。3 文字以上の語は FTS5 trigram、3 文字未満の語は全文ファイルの部分一致。語は FTS5 に渡すとき `"` で囲み、内部の `"` を二重にする）

- [ ] **Step 1: Write the failing tests**: `test_search_three_chars_uses_fts`、`test_search_two_chars_japanese`（「契約」）、`test_search_and_of_short_and_long_terms`、`test_search_special_chars_do_not_raise`（`'"foo" (bar) -baz*'`。Review Focus 5）、`test_rebuild_after_deleting_index_and_text`（`index.db` と `text/` を消して `rebuild` すると、同じ検索結果。受入条件 24）、`test_ensure_rebuilds_when_missing`、`test_search_ignores_placing_docs`。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_index.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。`sqlite3` で `CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, body, tokenize='trigram')`。trigram が使えない SQLite の場合は、`RuntimeError("fts5 trigram unavailable")` を送出する。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add trigram search index with short-term fallback"`

---

### Task 5: 取り込み（`intake`）と配置（`place`）

**Files:**
- Create: `scripts/vault_inbox/place.py`、`tests/test_place.py`
- Modify: `scripts/vault_inbox.py`（`intake`・`place`・`resume` を登録）

**Interfaces:**
- Consumes: Task 1 の `DEPTH_LIMIT`・`SUPPORTED_EXTS`、Task 2 の `MetaStore`・`Doc`・`file_hash`・`new_id`、Task 3 の `extract_text`・`ExtractError`・`is_candidate`、Task 4 の `save_text`・`rebuild`。
- Produces（`place.py`）:
  - `clamp_dest(dest_rel: str) -> str`（`/` 区切りの分類先を 5 階層に切り詰める。先頭は `project` か `shared` でなければ `ValueError`）
  - `class NameCollision(Exception)`
  - `intake(root: Path, store: MetaStore) -> list[dict]`: `inbox/` 直下のファイルを 1 件ずつ調べ、`{"name", "status", "reason", "id", "hash", "text_path"}` を返す。`status` は `"ready"`（抽出成功・同じ `hash` なし。`id` を採番し、全文を `text/` に保存する）、`"duplicate"`（`reason` に既存の `path`。同じバッチの先に `ready` となったものも含む）、`"unsupported"`、`"extract_failed"`、`"skipped"`（`is_candidate` が False）。`inbox/` のサブフォルダは `"skipped"`（`reason: "subfolder"`）
  - `place(root, store, name: str, dest_rel: str, doc_id: str, hash: str, date: str, tags: list[str], summary: str) -> Doc`: `clamp_dest` した分類先にフォルダを作り、`Doc(state="placing")` を保存してから、原本を `inbox/<name>` から移し、`state="active"` にして保存し、索引を更新する。分類先に同名の別内容の原本があれば `NameCollision`（何も動かさない）。
  - `resume_placing(root, store) -> list[str]`: `state=="placing"` の資料を完了させる（原本が `inbox/` に残っていれば移動から、分類先にあれば登録から。どちらにもなければ `store.remove`）。完了した `id` を返す。
- Produces（CLI）: `intake` → `{"items": [...]}`、`place --name --dest --id --hash --date --tags a,b --summary S` → `{"doc": {...}}` か `{"error": "name_collision"}`（終了コード 0）、`resume` → `{"resumed": [...]}`。

- [ ] **Step 1: Write the failing tests**: `test_clamp_dest_truncates_to_five`（`project/a/b/c/d/e/f` → `project/a/b/c/d/e`。受入条件 5）、`test_clamp_dest_rejects_other_roots`、`test_intake_ready_and_text_saved`、`test_intake_duplicate_of_registered`、`test_intake_duplicate_within_same_batch`（2 つ目が duplicate）、`test_intake_unsupported_and_extract_failed_stay`（`.doc`・壊れた PDF・空ファイル。Review Focus 1）、`test_intake_skips_office_temp_and_subfolders`（Review Focus 4）、`test_place_moves_original_unchanged`（移動後の `file_hash` が移動前と `Doc.hash` に一致。受入条件 3・4）、`test_place_name_collision_leaves_inbox_file`（受入条件 17）、`test_place_japanese_name_with_spaces`（Review Focus 2）、`test_resume_after_crash_between_move_and_register`（`state="placing"` で原本が分類先にある → `resume_placing` で `active`）、`test_resume_when_original_still_in_inbox`。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_place.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。`inbox/` から分類先への移動は `shutil.move`。`Doc.path` は Vault ルートからの `/` 区切り。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add intake and placement with resume"`

---

### Task 6: 追従の検出と解決（`scan`・`resolve`）

**Files:**
- Create: `scripts/vault_inbox/scan.py`、`tests/test_scan.py`
- Modify: `scripts/vault_inbox.py`（`scan`・`resolve` を登録）

**Interfaces:**
- Consumes: Task 2 の `MetaStore`・`file_hash`、Task 3 の `extract_text`・`is_candidate`、Task 4 の `save_text`・`rebuild`、Task 1 の `SUPPORTED_EXTS`。
- Produces（`scan.py`）:
  - `scan(root: Path, store: MetaStore) -> dict`: `project/`・`shared/` を調べる（`_index.md`・`is_candidate` が False・対象外の拡張子は除く）。次を返す（戻す前に、確認なしで済む分は `store` に反映して `save()` する）:
    - `"moved": [{"id","from","to"}]`（`active` の資料のパスが消え、同じ `hash` の新しい原本がある → 場所を更新）
    - `"updated": [{"id","path"}]`（パスが同じで `hash` だけ変わった → `hash` を更新し、全文を `save_text` で更新して、`rebuild` する。要約・タグ・日付の作り直しは呼び出し側（SKILL.md）の仕事）
    - `"duplicates": [{"path","same_as"}]`（登録のない原本で、`hash` が登録済みの資料と同じ。`notified_dup` 済みは含めない。含めたら `mark_dup`）
    - `"unresolved": [{"kind", ...}]`: `kind` は `"missing_and_new"`（`missing: [{"id","path"}]` と `new: [{"path","hash"}]` の両方があるとき、1 件にまとめる）、`"missing"`（`id`, `path`）、`"new"`（`path`, `hash`）。`is_ignored(path, hash)` の新しい原本は含めない。
  - `resolve(root, store, action: str, **kw) -> dict`: `action` は `"regroup"`（`missing_id`, `new_path`: 消えた資料の `id` と関係を新しい原本に引き継ぎ、`path`・`hash` を更新し、全文を更新）、`"drop"`（`id`: メタデータと関係を消す。ファイルは消さない）、`"ignore"`（`path`: `store.ignore(path, 現在の hash)`）。「新規として登録する」は、SKILL.md が `intake` と同じ手順（`id` 採番・全文保存・`place` 相当の登録）で行うので、`action="register"`（`path`, `date`, `tags`, `summary`; 原本は動かさず、その場所のまま `Doc` を登録し、全文を保存する）も実装する。「保留する」は何もしない。
- Produces（CLI）: `scan` → 上の辞書、`resolve --action A --missing-id I --new-path P --id I --path P ...` → `{"ok": true}`。

- [ ] **Step 1: Write the failing tests**: `test_moved_when_hash_same_path_changed`（受入条件 7。関係が `id` のまま残る）、`test_renamed_in_same_folder`、`test_updated_when_hash_changed_in_place`（確認なし。全文と索引が更新される）、`test_unresolved_missing_and_new_when_edited_and_moved`、`test_unresolved_missing_only_when_deleted`、`test_unresolved_new_when_user_drops_file_in_project`、`test_duplicate_copy_reported_once`（2 回目の `scan` では出ない）、`test_index_md_and_unsupported_files_are_ignored`、`test_regroup_keeps_id_and_relations`、`test_drop_removes_relations_but_keeps_file`、`test_ignore_suppresses_until_hash_or_path_changes`（受入条件 8）、`test_scan_is_idempotent`（2 回続けて呼ぶと 2 回目は `moved`・`updated` が空）。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_scan.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。`moved` の突き合わせは `hash` で行い、同じ `hash` の候補が複数あるときは `unresolved` に回す。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add follow-up scan and resolve"`

---

### Task 7: 関係の記録・行き先なしの検出・展開

**Files:**
- Create: `scripts/vault_inbox/relations.py`、`tests/test_relations.py`
- Modify: `scripts/vault_inbox.py`（`search`・`relate`・`dangling`・`expand`・`kind-add` を登録）

**Interfaces:**
- Consumes: Task 2 の `MetaStore`、Task 4 の `search`・`ensure`。
- Produces（`relations.py`）:
  - `dangling(store: MetaStore) -> list[dict]`（`src` か `dst` が `active` の資料でない関係。`{"src","dst","kind"}`）
  - `expand(store: MetaStore, hit_ids: list[str]) -> dict`: 返り値は `{"materials": list[str], "conflicts": list[list[str]]}`。`materials` は、`hit_ids` と、それらに直接つながる資料（関係の `src`・`dst` の両方向、1 つ先まで）の和集合（出現順、重複なし）から、`supersedes` の `dst`（旧版）を除いたもの。`conflicts` は、`materials` に含まれる資料どうしの `conflicts_with` の組。
- Produces（CLI）: `search --query Q` → `{"ids": [...], "docs": [{id,path,summary}]}`（`ensure` を先に呼ぶ）、`expand --ids a,b` → 上の辞書に `docs` を足したもの、`relate --src --dst --kind` → `{"ok": true}`（語彙外は `{"error":"unknown_kind"}`）、`kind-add --kind K`、`dangling` → `{"relations": [...]}`、`relation-remove --src --dst --kind`。

- [ ] **Step 1: Write the failing tests**: `test_expand_one_hop_both_directions`（B がヒット、A→B の関係 → A が入る。受入条件 12）、`test_expand_does_not_reach_two_hops`（A→B→C で A がヒット → B は入り C は入らない）、`test_expand_drops_superseded_even_when_direct_hit`、`test_expand_reports_conflicts`、`test_dangling_after_drop`（受入条件 9）、`test_expand_with_no_relations_returns_hits`。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_relations.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add relations, expansion and search commands"`

---

### Task 8: `_index.md` の生成

**Files:**
- Create: `scripts/vault_inbox/indexmd.py`、`tests/test_indexmd.py`
- Modify: `scripts/vault_inbox.py`（`indexmd` を登録）

**Interfaces:**
- Consumes: Task 2 の `MetaStore`、Task 1 の定数。
- Produces（`indexmd.py`）:
  - `link_for(rel_path: str) -> str`（拡張子が `.md`・`.pdf`・`.png`・`.jpg`・`.jpeg` なら `[[名前.拡張子]]`、それ以外はファイル名のテキスト）
  - `write_index_files(root: Path, store: MetaStore) -> list[str]`: `active` の資料がある、または資料のあるサブフォルダを持つ `project/`・`shared/` 配下の各フォルダに `_index.md` を作り直す（書いた `_index.md` の相対パスを返す）。内容は、`# <フォルダ名>`、「資料」節（直下の資料ごとに `link_for` と要約）、「サブフォルダ」節（`[[サブ/_index|サブ]]`）、「関係」節（そのフォルダ直下の資料が `src` か `dst` の関係を `src の link — kind → dst の link` で。起点側と行き先側の両方のフォルダに載る）。資料も関係もなくなったフォルダの `_index.md` は消す。`inbox/`・`.vault-inbox/` には作らない。

- [ ] **Step 1: Write the failing tests**: `test_link_for_obsidian_openable_vs_office`（`.pdf` は `[[...]]`、`.docx` はテキスト。受入条件 14）、`test_index_lists_docs_and_subfolders`、`test_relation_appears_in_both_folders`（受入条件 11）、`test_moved_doc_leaves_old_folder_index`（受入条件 7）、`test_empty_folder_index_removed`、`test_no_index_in_inbox_or_vault_dir`、`test_index_regeneration_overwrites_manual_edits`。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_indexmd.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: generate _index.md with relations"`

---

### Task 9: 排他と変化の検知（`watch` の部品）

**Files:**
- Create: `scripts/vault_inbox/lock.py`、`scripts/vault_inbox/watch.py`、`tests/test_lock.py`、`tests/test_watch.py`
- Modify: `scripts/vault_inbox.py`（`lock`・`unlock`・`snapshot`・`watch` を登録）

**Interfaces:**
- Produces（`lock.py`）:
  - `acquire(root: Path, owner: str, stale_after: float = 600.0) -> bool`（`.vault-inbox/lock.json` に `{"owner","pid","time"}` を `O_EXCL` で作る。すでにあり、`time` が `stale_after` 秒以内なら False。それより古ければ上書きして True）、`release(root, owner) -> None`（`owner` が一致するときだけ消す）、`holder(root) -> dict | None`
  - `owner` は `"organize"`・`"watch"`・`"ask-record"`。`organize`・`watch` は、他の `owner` が保持していれば断る。`ask-record` は断らず、`wait_for_free(root, timeout: float = 60.0) -> bool` で待つ。
- Produces（`watch.py`）:
  - `snapshot(root: Path) -> dict[str, list[int]]`（`inbox/`・`project/`・`shared/` を再帰し、`_index.md` と `.files`・`.obsidian`・`.vault-inbox` を除いた各ファイルの相対パス → `[mtime_ns, size]`）
  - `save_baseline(root)`（現在の `snapshot` を `.vault-inbox/watch_baseline.json` に保存）、`changed(root) -> bool`（現在とベースラインが違う）
  - `poll(root: Path, interval: float, settle: float, once: bool = False) -> Iterator[str]`: `interval` 秒ごとに `changed` を調べ、違いが見つかったら、`settle` 秒の間 `snapshot` が変わらなくなるまで待ってから `"CHANGED"` を 1 行 yield する。`once=True` なら、1 回 yield（または 1 回の判定）で終わる。ベースラインを更新するのは `save_baseline` だけ（`organize` の最後と `watch` の起動直後に呼ぶ）。
- Produces（CLI）: `lock --owner O` → `{"acquired": bool, "holder": {...}|null}`、`unlock --owner O`、`snapshot-save`、`watch --interval 5 --settle 3`（標準出力に `CHANGED` を 1 行ずつ出し続ける。Monitor 用。起動時に、すでに `watch` の `lock` が保持されていれば `{"error":"already_running"}` を 1 行出して終了）。

- [ ] **Step 1: Write the failing tests**: `test_lock_second_acquire_refused`（受入条件 21）、`test_lock_stale_is_taken_over`、`test_release_only_by_owner`、`test_wait_for_free_returns_after_release`、`test_snapshot_excludes_index_md_and_hidden_dirs`（受入条件 20）、`test_changed_false_right_after_baseline`（organize 自身の書き込み後に `save_baseline` すれば反応しない）、`test_changed_true_after_new_file`、`test_poll_waits_for_settle`（ファイルを段階的に書き続けている間は yield せず、止まってから 1 回だけ yield）、`test_poll_yields_once_for_duplicate_events`（受入条件 19）。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_lock.py tests/test_watch.py -v`。Expected: FAIL。
- [ ] **Step 3: Implement** 上記。ベースラインは、`save_baseline` を呼ぶまで進めない。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add lock and change detection for watch"`

---

### Task 10: 4 つの SKILL.md

**Files:**
- Create: `skills/init/SKILL.md`、`skills/organize/SKILL.md`、`skills/watch/SKILL.md`、`skills/ask/SKILL.md`
- Test: `tests/test_skills.py`（構造の検査のみ）

**Interfaces:**
- Consumes: Task 1〜9 の CLI（`status`・`init`・`resume`・`scan`・`resolve`・`intake`・`place`・`indexmd`・`search`・`expand`・`relate`・`kind-add`・`dangling`・`relation-remove`・`lock`・`unlock`・`snapshot-save`・`watch`・`rebuild`）。`rebuild` は `index.rebuild` を呼ぶサブコマンドとして、この Task で `vault_inbox.py` に足す。
- Produces: 各 SKILL.md の frontmatter は `name`（`init`・`organize`・`watch`・`ask`）と `description`。本文は、日本語で、次の手順を、スクリプトの呼び出しと AskUserQuestion の位置が分かる形で書く。スクリプトは `python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" <cmd> --root .` で呼ぶ。

- [ ] **Step 1: Write the failing test** `tests/test_skills.py`: `test_each_skill_has_frontmatter_and_calls_script`（4 つの `SKILL.md` に `name:` と `description:` があり、`vault_inbox.py` を含む）、`test_organize_skill_mentions_every_decision_point`（`organize/SKILL.md` に `AskUserQuestion`・`unresolved`・`dangling`・`duplicate`・`name_collision`・`resume`・`rebuild`・`lock` が含まれる）、`test_ask_skill_mentions_no_save_and_options_for_relations`。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests/test_skills.py -v`。Expected: FAIL。
- [ ] **Step 3: Write the four SKILL.md files:**
  - **init**: `status` を呼び、`has_obsidian` が False なら AskUserQuestion（続行する・やめる）。やめるなら何もしない。続行なら `init` を実行して、作ったフォルダを知らせる。
  - **organize**: `status` で未初期化なら `init` を案内して止まる。`lock --owner organize` が取れなければ、実行中であることを知らせて止まる。次の順で行う: ① `rebuild`（索引・全文が欠けていれば作り直す） ② `resume` ③ `scan`: `updated` の資料は全文を読んで要約・タグ・日付を作り直し、メタデータを更新する。`duplicates` は 1 回知らせる。`unresolved` は資料ごとに、状態に応じた AskUserQuestion（`missing_and_new`=組み直す・新規として登録する・索引から外す、`missing`=索引から外す・保留する、`new`=新規として登録する・登録しない）で確認し、`resolve` で反映する。`dangling` は関係ごとに AskUserQuestion（消す・残す）で確認し、`relation-remove` で反映する ④ `intake` の `ready` を 1 件ずつ: 全文を読んで要約・タグ・日付を作り、`project/`・`shared/` の既存のフォルダを見て分類先を選ぶ（5 階層以内、タグは既存のタグを再利用）。既存に合うものがなければ、新しい分類先を AskUserQuestion の選択肢で提案して承認を得る（承認されなければ `inbox/` に残す）。`place` を呼び、`name_collision` なら `inbox/` に残す ⑤ `indexmd` ⑥ `snapshot-save` ⑦ `unlock --owner organize`。最後に、`inbox/` に残した資料（`duplicate`・`unsupported`・`extract_failed`・`name_collision`・承認されなかった資料）を、理由つきの一覧で知らせる。途中で失敗しても `unlock` する。
  - **watch**: `status` で未初期化なら `init` を案内して止まる。Monitor が使えなければ、使えないことを知らせて `organize` を案内して終わる。`lock --owner watch` が取れなければ、実行中であることを知らせて終わる。起動直後に `organize` の手順を 1 回実行する（`organize` の `lock` はこの `watch` の保持と衝突しないよう、`--owner watch` のまま手順を実行する）。そのあと Monitor で `watch --interval 5 --settle 3` を起動し、`CHANGED` が来るたびに `organize` の手順を実行する。確認（AskUserQuestion）の応答待ちの間に来た `CHANGED` は、溜めて、確認のあとで 1 回にまとめる。停止は、セッションを閉じるか、Monitor の停止の操作で、止めるときは `unlock --owner watch` を呼ぶ。
  - **ask**: `status` で未初期化なら `init` を案内して止まる。`search --query` の結果が 0 件なら「該当する資料がない」と答えて終わる（推測しない）。結果の `ids` を `expand` に渡し、`materials` の全文を読んで回答を作る。回答に、根拠にした資料の原本へのリンク（Obsidian が開ける形式は `[[リンク]]`、それ以外はファイル名のテキスト）を付け、`conflicts` は矛盾として併記する。回答は保存しない。回答のあと、見つけた関係の候補があれば、AskUserQuestion の選択肢（複数選択）で提示し、語彙にない種類は、新しい種類の追加を選択肢で承認を得る。承認された分だけ、`wait_for_free` 相当（`lock --owner ask-record` が取れるまで待つ）のあとで `relate`（必要なら `kind-add`）→ `indexmd` を実行する。候補が 0 件なら何も聞かずに終わる。
- [ ] **Step 4: Run** 同じコマンド。Expected: PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: add skills for init, organize, watch and ask"`

---

### Task 11: 通し試験と実機確認の手順

**Files:**
- Create: `tests/test_e2e.py`、`vault-inbox/README.md`

**Interfaces:**
- Consumes: すべての CLI。

- [ ] **Step 1: Write the failing test** `tests/test_e2e.py`（一時 Vault で、`subprocess` から CLI を順に呼ぶ。Claude の判断は、テストが `place` の引数として直接与える）: `test_e2e_init_intake_place_search_relate_ask`（`init` → `inbox/` に `.md`・`.txt`・`.html`・`.docx` を置く → `intake` → `place` → `indexmd` → `search "契約"` が 2 文字の語で当たる → `relate` → `expand` で関係先が `materials` に出る → `indexmd` で両フォルダの `_index.md` に関係が出る。受入条件 1・3・11・12・13・14）、`test_e2e_user_moves_and_edits_then_scan`（原本を別フォルダへ移し、別の原本を編集 → `scan` → 受入条件 7）、`test_e2e_uninitialized_vault_reports_status`（受入条件 2: `status` が `initialized: false`）、`test_e2e_rebuild_matches_after_deleting_index`（受入条件 24）。
- [ ] **Step 2: Run** `python -X utf8 -m pytest tests -v`。Expected: 新しいテストが FAIL、その他は PASS。
- [ ] **Step 3: Fix** 通し試験で見つかった不整合を、該当する Task のファイルで直す。`README.md` に、導入（`pip install -r requirements.txt`）と、**実機確認の手順（受入条件 0・18・19・20・22・25）** を書く: ① 実際の Obsidian の Vault で、`_index.md` の `[[リンク]]` がバックリンク・グラフに出ること、`.vault-inbox/` が一覧・検索に出ないこと ② `/vault-inbox:watch` を起動し、起動直後に `inbox/` の資料が整理されること ③ `watch` 中に資料を置く・動かす・編集すると自動で整理され、`organize` 自身の書き込みで再実行されないこと ④ セッションを閉じる、または停止の操作で止まること ⑤ Monitor が使えない環境で、案内されること。
- [ ] **Step 4: Run** `python -X utf8 -m pytest tests -v`。Expected: すべて PASS。
- [ ] **Step 5: Commit** `git add -A && git commit -m "test: add end-to-end checks and manual verification guide"`

---

## Self-Review

- **Spec coverage:** 受入条件 0（README の手順）、1・2（Task 1・10）、3・4・5・6・17（Task 5・10）、7・8（Task 6・10）、9（Task 7・10）、10・12・23（Task 7・10）、11（Task 7・8・10）、13（Task 4）、14（Task 8）、15・16（Task 5・10）、18〜22・25（Task 9・10・README）、24（Task 4）。
- **Type consistency:** `MetaStore`・`Doc`・`file_hash`・`new_id`（Task 2）を Task 4〜8 が同じ名前で使う。`save_text`・`rebuild`・`ensure`・`search`（Task 4）は Task 5〜7 が使う。`lock`の `owner` は `"organize"`・`"watch"`・`"ask-record"` の 3 つで統一。
- **決めていないこと（実装中に判断してよい）:** `watch` の既定の `--interval 5 --settle 3`（SKILL.md に書いた値）、`.xlsx` のセルの連結の細部、`index.db` のスキーマの細部。

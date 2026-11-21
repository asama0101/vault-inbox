---
name: init
description: Vault を vault-inbox 用に初期化する（inbox/・project/・shared/・.vault-inbox/ を作る）。初めて使うときに実行する。
disable-model-invocation: true
---

# vault-inbox 初期化

スクリプトは次の形で呼ぶ（以下 `SCRIPT <cmd>` と書く）。出力は 1 行の JSON。

`python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" <cmd> --root='.'`

## 手順

1. `SCRIPT status` を実行する。`{"initialized": ..., "has_obsidian": ..., "missing_deps": [...]}` が返る。
   - `missing_deps` が空でなければ、PDF・Office の資料が読めないことを知らせ、次の導入を案内する（`missing_deps` の各名前が入っていない）。導入が済むまで資料が `inbox/` に残る（理由は `missing_dependency`）が、初期化は続けてよい。

     `python -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`
2. `has_obsidian` が false（`.obsidian/` がない）なら、AskUserQuestion で聞く。選択肢は「続行する」「やめる」。
   - 「やめる」なら、何も作らずに終わる。
3. `SCRIPT init` を実行する。返った `created` が、作ったフォルダの一覧になる。
4. 作ったフォルダを知らせる。`created` が空なら「すでに初期化済み」と知らせる。次は `organize`（`inbox/` に資料を置いてから）を案内する。

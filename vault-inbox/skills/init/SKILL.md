---
name: init
description: Vault を vault-inbox 用に初期化する（inbox/・project/・shared/・.vault-inbox/ を作る）。初めて使うときに実行する。
disable-model-invocation: true
allowed-tools:
  - AskUserQuestion
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" status *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" init *)
---

# vault-inbox 初期化

Vault（資料を置いたフォルダ）を vault-inbox 用に初期化する。`inbox/`・`project/`・`shared/`・`.vault-inbox/` を作り、資料を置いて `organize` で整理できる状態にする。初めて使うときに 1 回実行する。

## 用語
| 用語 | 意味 |
|---|---|
| `SCRIPT <cmd>` | スクリプトのサブコマンド `<cmd>` を呼ぶこと（呼び方は「コマンドの呼び方」の節）。出力は 1 行の JSON |
| `missing_deps` | 入っていない Python のライブラリの名前の一覧。PDF・Office の資料を読むために要る |

## コマンドの呼び方
スクリプトを次の形で呼ぶ（`<cmd>` がサブコマンド。以下 `SCRIPT <cmd>` と書く）。

`python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" <cmd> --root='.'`

`python` が見つからず `SCRIPT status` が失敗したら（Microsoft Store を開くよう求める表示を含む）、Python 3.10 以上を入れて `python` で起動できるようにするよう案内して止まる。`py`・`python3` など、別の起動コマンドは試さない（承認の確認が増え、ほかの手順と合わなくなる）。

## 手順

### 手順1: 状態を確かめる
目的: 初期化済みか、足りないライブラリがないかを知る。
- 状態を読む。`SCRIPT status` を実行する。`{"initialized": ..., "has_obsidian": ..., "missing_deps": [...]}` が返る。
- `missing_deps` が空でなければ、PDF・Office の資料が読めないことを知らせ、次の導入を案内する（`missing_deps` の各名前が入っていない）。導入が済むまで資料が `inbox/` に残る（理由は `missing_dependency`）が、初期化は続けてよい。

  `python -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`

### 手順2: Obsidian の有無を確かめる
目的: Obsidian の Vault でないフォルダに作ってしまわないよう、利用者に確かめる。
- `has_obsidian` が false（`.obsidian/` がない）なら、AskUserQuestion で聞く。選択肢は「続行する」「やめる」。
- 「やめる」なら、何も作らずに終わる。

### 手順3: 初期化する
目的: フォルダを作る。
- フォルダを作る。`SCRIPT init` を実行する。返った `created` が、作ったフォルダの一覧になる。

### 手順4: 結果を知らせる
目的: 何を作ったか、次に何をするかを伝える。
- 作ったフォルダを知らせる。`created` が空なら「すでに初期化済み」と知らせる。次は `organize`（`inbox/` に資料を置いてから）を案内する。

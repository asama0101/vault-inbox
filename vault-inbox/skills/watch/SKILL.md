---
name: watch
description: Vault の変更を監視し、変更があるたびに organize の手順を自動で実行する（Monitor が必要）。
disable-model-invocation: true
allowed-tools:
  - AskUserQuestion
  - Monitor
  - Read
  - Glob
  - Write
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" status *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" lock *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" unlock *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" snapshot-save *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" rebuild *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" resume *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" scan *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" update-meta *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" resolve *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" dangling *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" relation-remove *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" relation-keep *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" intake *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" inbox-mark *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" place *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" indexmd *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" snapshot-absorb *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" watch *)
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" changed *)
---

# 監視しながら整理

スクリプトは次の形で呼ぶ（以下 `SCRIPT <cmd>` と書く）。

`python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" <cmd> --root='.'`

確認・承認は、すべて AskUserQuestion の選択肢で行う。

## 手順

1. `SCRIPT status` を実行する。`initialized` が false なら、`init` を案内して止まる。
2. Monitor ツールが使えなければ、使えないことを知らせ、代わりに `organize` を案内して終わる。
3. 先に Monitor で次のコマンドを起動する。このコマンドが、起動時に `watch` のロックを取り、基準（スナップショット）を保存し、変更が落ち着くたびに標準出力へ `CHANGED` を 1 行出す。このスキルは `lock --owner watch` を自分では呼ばない。

   `python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" watch --interval='5' --settle='3' --root='.'`

   最初の出力が `{"error": "already_running"}` なら、「すでに実行中です」と知らせて終わる。
4. そのあとで、初回として「organize」の手順を 1 回実行する。`session` のロックは `watch`（Monitor のコマンド）が持っているので、owner `organize` のロックは取らない（`organize` の「準備」の 2 と、仕上げの `session` の `unlock` は行わない）。`pass` のロック（`--name pass`）は、`organize` の手順のとおり、実行ごとに owner `watch` で取り、終わったら解除する。
5. `CHANGED` の行が来るたびに、先に `SCRIPT changed` を実行する。`changed` が false なら（前の実行が、自分の書き込みのあとで基準を保存し終えている）、その回は何もしない。true なら、`organize` の手順（`pass` のロックと `snapshot-save` から、`snapshot-absorb` と解除まで）を実行する。この 2 回目以降の実行では、`inbox/` に残る資料は、`seen` が false のものだけを知らせる（`organize` の ④ のとおり）。
   - 実行が済んだら、もう一度 `SCRIPT changed` を実行する（初回の実行のあとも）。true なら（確認の応答待ちの間に置かれた・変えられた資料などが、まだ処理されていない）、続けてもう 1 回だけ実行する。その追加の実行のあとは `changed` を確かめず、次の `CHANGED` を待つ（追加の実行は、`CHANGED` 1 回・初回の実行 1 回につき、最大 1 回）。
   - 確認（AskUserQuestion）の応答待ちの間に来た `CHANGED` は、溜めておく。確認が終わって実行が済んだあとで、1 回にまとめて実行する。
   - 実行が失敗しても、監視は続ける。失敗は利用者に知らせる。
6. 停止は、セッションを閉じるか、Monitor の停止の操作で行う。後始末として `SCRIPT unlock --owner='watch'` も実行する。

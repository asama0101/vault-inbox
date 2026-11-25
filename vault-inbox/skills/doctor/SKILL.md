---
name: doctor
description: vault-inbox が動くために必要なもの（Python の版、保存先、PDF・Office 用のライブラリ、SQLite の FTS5）を確認し、プラグインが最新かも知らせる。足りないものと直し方を伝える。「vault-inbox の環境を確認して」「doctor」「動かない原因を調べて」と頼まれたときに使う。資料の整理・検索には使わない（organize・ask）。
disable-model-invocation: true
allowed-tools:
  - Bash(python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" doctor *)
---

# doctor

vault-inbox の動作環境を確認する。何も変更しない。

## 手順

1. 環境の点検コマンドを 1 回だけ実行する。やり直さない。

   `python -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/vault_inbox.py" doctor --data "${CLAUDE_PLUGIN_DATA}"`

   `python` が見つからず失敗したら（Microsoft Store を開くよう求める表示を含む）、Python 3.10 以上を入れて `python` で起動できるようにするよう案内して止まる。`py`・`python3` など、別の起動コマンドは試さない（承認の確認が増え、ほかの手順と合わなくなる）。

2. 出力を、日本語で短く知らせる。
   - `[OK]` の行は、一言でまとめる。
   - `[情報]` の行は、プラグインのバージョンと最新版の確認結果なので、そのまま伝える。新しい版があると出たときは、`→` の更新のコマンドも伝える（自分では実行しない）。
   - `[任意]` の行は、PDF・Office の資料を読むときだけ要るライブラリが入っていないことを示す。`→` の導入コマンドを伝える（自分では実行しない）。入っていなくても、md などの資料は整理できる。
   - `[NG]` の行があるときは、1 行ずつ伝える。直し方は、出力の `→` の行を伝える。自分では何も入れない。
     - `[NG] 実行環境`: Python 3.10 以上が要る
     - `[NG] 保存先`: 書き込めない
     - `[NG] SQLite FTS5 trigram`: 検索（`ask`）が動かない
3. 初期化の状態（`init` 済みか）は、このスキルでは調べない。Vault で `organize` などが「初期化されていない」と止まったときに、`/vault-inbox:init` を案内する。

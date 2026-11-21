# ロックが残ったとき

[README の「困ったとき」](../README.md#困ったとき)から来た手順。

> **警告**: 動いている `organize` か `watch` がないことを確認してから実行する。動作中に解放すると、二重に実行される。

`organize` や `watch` が強制終了されると、ロックが残る。`watch` のロックは約 30 秒、`organize` のロックは約 1 時間（確認の返事を待つ間に切れないため）で、自動で解放される。すぐ解放するときは、Vault のルートで次を実行する。`<owner>` は、出力の `holder` にある owner（`organize`・`watch`・`ask-record`）にする。owner が違うと、何も解放されないのに `{"ok": true}` が返る。

`<このリポジトリ>` は、clone して入れた場所。マーケットプレイスで入れたときは、プラグインの導入先にする。場所が分からないときは、Claude Code に「vault-inbox のロックを解放して」と頼む。

```
python -X utf8 <このリポジトリ>/vault-inbox/scripts/vault_inbox.py unlock --owner <owner> --name session --root .
python -X utf8 <このリポジトリ>/vault-inbox/scripts/vault_inbox.py unlock --owner <owner> --name pass --root .
```

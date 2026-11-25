# CLAUDE.md

このリポジトリは、Claude Code プラグイン `vault-inbox`（`vault-inbox/`）と、その文書（`docs/`）。

## 確認コマンド

- テスト: `python -m pytest`
- lint: `python -m ruff check .` と `python -m ruff format --check .`

## docs の更新ルール

次の表は、変更したものと、同じ PR で見直す文書を示す。

| 変更したもの | 見直す文書 |
|---|---|
| `skills/organize/`・`skills/ask/` の SKILL.md・手順書、スクリプトの出力の書式、md のプロパティの書式 | `docs/organize-ask/`（解説ページ）。使い方は [docs/development.md](docs/development.md) |

- 解説ページ（`docs/organize-ask/page.html`）に、写しを書かない。全文・ファイルの大きさ・版・行番号・標準出力・件数は、`build.py` が生成のたびに、リポジトリから読む（または実行して採取する）。`page.html` には `{{名前}}` を書く。
- 手順書・スクリプトの出力・フォームを変えたら、同じ PR で、`build.py` を実行して、次を確かめる。
  - 実行が失敗しない（デモの手順が、変更後のスクリプトで通る）。
  - `page.html` の解説（「解説」ラベルの枠・カード・表）が、新しい本文・出力と食い違わない。
- 公開した Artifact は、リポジトリと連動しない。変更後は、再生成して再公開する。
- `page.html` の 5 章（止まる条件）・6 章（判断の規則）・3 章（カード）は、手で書いた解説である。スクリプトや手順書を変えたら、見直す。
- 生成したページは、リポジトリに入れない（出力先は、リポジトリの外）。

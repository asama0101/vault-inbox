# CLAUDE.md

このリポジトリは、Claude Code プラグイン `vault-inbox`（`vault-inbox/`）と、その文書（`docs/`）。

## 確認コマンド

- テスト: `python -m pytest`
- lint: `python -m ruff check .` と `python -m ruff format --check .`

## 版を上げるとき

次の 2 か所の `version` を、同じ値にそろえる。

- `vault-inbox/.claude-plugin/plugin.json`
- `pyproject.toml`

# 開発者向けの情報

利用者向けの説明は [README.md](../README.md)。Claude が守る規則は [CLAUDE.md](../CLAUDE.md)。ここは、このリポジトリを直す人向けの、準備・構成・版の手順。

## 準備

開発用の依存は `requirements-dev.txt`（pytest・ruff など）。`.venv/` は Git 管理外で、リポジトリ直下に作って依存を入れる。確認のコマンドは、CLAUDE.md の「確認コマンド」にある。

## 構成

- `vault-inbox/skills/`: スキル（`init`・`doctor`・`organize`・`ask`・`watch`）。`organize` には `references/` の手順書がある。
- `vault-inbox/scripts/vault_inbox/`: スキルから呼ぶ Python のスクリプト。
- `vault-inbox/tests/`: テスト（`pyproject.toml` の `testpaths`）。
- `vault-inbox/.claude-plugin/plugin.json`: プラグインのマニフェスト。

## 版を上げる

次の 2 か所の `version` を、同じ値にそろえる。

- `vault-inbox/.claude-plugin/plugin.json`
- `pyproject.toml`

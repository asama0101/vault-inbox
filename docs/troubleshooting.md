# 困ったとき

最終報告に出る主な理由（`inbox/` に残る資料）と、画面の表示ごとの対処。

| 理由・表示 | 対処 |
|---|---|
| `duplicate` | 同じ中身の資料が既にある。放置してよい。 |
| `unsupported` | 対象外の形式（`.doc`・`.xls`・`.ppt`・画像・csv・json・zip）。変換して置く。 |
| `extract_failed` | スキャン PDF・壊れた・パスワード付きの資料。 |
| `missing_dependency: <pip 名>` | `/vault-inbox:init` か `doctor` が示すコマンドで入れる。 |
| `name_collision` | 分類先に同名で内容が違う資料がある。名前を変えて置き直す。 |
| 未承認 | 分類先を承認しなかった。内容が変わるまで聞き直さない。 |
| 初期化されていません | `/vault-inbox:init` を実行する。 |
| `already_running`（`holder`） | 終わるのを待つ。止めた後も出るなら、`watch` は約 30 秒、`organize` は約 1 時間待つか、[ロックの解放](docs/stale-lock.md)をする。 |
| `[NG]`・`python` が見つからない | `[NG]` の次の行の対処に従う。スキルは `python` で起動するので、Python 3.10 以上を入れて `python` で起動できるようにする（`py`・`python3` では、スキルは動かない）。手で `doctor` を打つときだけは、Windows の `py -3 -X utf8` で代用できる。 |
| Monitor が使えない | `watch` の代わりに `/vault-inbox:organize` を実行する。 |
| `bad_name` | ファイル名が正しくない。名前を変えて置き直す。 |
| `skipped` | サブフォルダ・`~$`・`.` で始まる名前・`.要約.md` で終わる名前は対象外。 |
| `failed` | 配置の途中で失敗した。資料は変わっていない。再実行する。 |

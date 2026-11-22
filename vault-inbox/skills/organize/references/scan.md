# organize 手順3: scan（手動で動かした資料への追従）

読むとき: organize の手順3 に入る直前。何のための手順書か: 利用者が手で動かした・書き換えた・消した資料を `scan` で見つけ、移動の追従、記録の更新、利用者への確認を行う。`SCRIPT`・`@ARGS`・全文の読み方・用語は、SKILL.md のとおり。

## scan の結果を扱う
`SCRIPT scan` を実行する（Vault の変化を調べる）。結果のキーごとに扱う。
- `moved`: 自動で追従済み。件数を知らせる。
- `updated`（中身が変わった資料。`id`・`path`）: 全文を `.vault-inbox/text/<id>.txt` から読み（SKILL.md の「全文の読み方」に従う）、要約・日付を作り直し、引数ファイルに `--id=<id>`・`--date=<日付>`・`--summary=<要約>` を書き、記録を更新する `SCRIPT update-meta @ARGS` で反映する。`{"error": "unknown_id"}` なら、知らせて次へ。
- `duplicates`（`path`・`same_as`）: 同じ中身の資料が既にある。1 回だけ知らせる（次回以降は出ない）。
- `failed`（`path`・`reason`）: 読み取れなかった資料。理由つきで知らせる。
- `unresolved`: 要素ごとに、`kind` に応じて AskUserQuestion で確認し、`resolve` で反映する（次の節）。
- `resolve` が `{"error": "bad_path"}` を返したら（`project/`・`shared/` の外、隠しフォルダ、ほかの資料が使っているパス）、知らせて次へ。

## unresolved の扱い
`kind` ごとに、次のとおりにする。`missing` は、記録にあるのに見つからなくなった資料。`new` は、記録にない新しい資料。
- `missing_and_new`（`missing` と `new` の配列）: 消えた資料ごとに、次を選択肢で聞く。
  - 「組み直す」: 相手の候補（`new` の各 `path`）を選択肢で示す。候補が 4 件を超えるときは、名前と内容が近いものから 3 件ずつ示し、4 つ目を「ほかの候補を見る」にする（最後の組は 4 件まで）。選ばれたら、引数ファイルに `--action=regroup`・`--missing-id=<id>`・`--new-path=<path>` を書き、`SCRIPT resolve @ARGS`。続けて、`updated` と同じく、全文 `.vault-inbox/text/<id>.txt` から要約・日付を作り直し、引数ファイルに `--id=<id>`・`--date=<日付>`・`--summary=<要約>` を書き、`SCRIPT update-meta @ARGS` で反映する（`regroup` は `path`・`hash`・全文しか更新せず、移動と同時に編集された資料の要約は古いままになる）。
  - 「新規として登録する」: 下の `new` の「登録する」と同じく、引数ファイルに `--action=register`・`--path=<path>`・`--date=<日付>`・`--summary=<要約>` を書き、`SCRIPT resolve @ARGS` で登録し、続けて `SCRIPT resolve --action='drop' --id='<消えた資料の id>'` で旧資料を索引から外す（旧資料の関係は、下の「関係の確認」で聞く）。
  - 「索引から外す」: `SCRIPT resolve --action='drop' --id='<id>'`。消えた資料（`missing` の側）に対する操作。`new` の側は、下の `new` の扱いで別に聞く。
  - 「新規として登録する」を選んだ組は、`new` の側を登録済みとして扱い、同じ資料を `new` の扱いで 2 度聞かない。
  - 選択肢は上の 3 つだけにする（「保留する」は足さない）。
- `missing`（`id`・`path`）: 「索引から外す」（`SCRIPT resolve --action='drop' --id='<id>'`）か「保留する」（何もしない。次回また聞く）。
- `new`（`path`・`hash`）: 「新規として登録する」か「登録しない」。
  - 登録する: 全文を読んで（SKILL.md の「全文の読み方」に従う）要約・日付を作り、引数ファイルに `--action=register`・`--path=<path>`・`--date=<日付>`・`--summary=<要約>` を書き、`SCRIPT resolve @ARGS`。
  - 登録しない: 引数ファイルに `--action=ignore`・`--path=<path>` を書き、`SCRIPT resolve @ARGS`（同じ中身は以後聞かない）。

## 関係の確認
資料が消えて、関係の相手がなくなった記録（dangling）を整理する。`SCRIPT dangling` を実行する。`relations`（`src`・`dst`・`kind`）の各関係について、AskUserQuestion で「消す」「残す」を聞く。引数ファイルに `--src=<src>`・`--dst=<dst>`・`--kind=<kind>` を書き、消すなら `SCRIPT relation-remove @ARGS`、残すなら `SCRIPT relation-keep @ARGS`（残した関係は、以後聞かない）。

# organize 手順4: intake（inbox の資料の配置）

読むとき: organize の手順4 に入る直前。何のための手順書か: `inbox/` の資料を 1 件ずつ読み、分類先へ配置するか、理由を付けて `inbox/` に残すかを決める。`SCRIPT`・`@ARGS`・全文の読み方・用語（報告の対象・`seen`・`hash`）は、SKILL.md のとおり。

## intake の結果を扱う
`SCRIPT intake` を実行する（`inbox/` の資料を調べ、配置できるかを返す）。`items`（`name`・`status`・`reason`・`id`・`hash`・`text_path`・`seen`）の `status` ごとに扱う。
- `ready` 以外（`duplicate`・`unsupported`・`extract_failed`・`skipped`・`declined`）: `inbox/` に残す。報告の対象なら、`reason` を控えて手順6 の最終報告に載せる（`declined` は、理由: 未承認）。そのあと、資料の状態を記録する。引数ファイルに `--name=<name>`・`--hash=<hash>`・`--status=<status>` を書き、`SCRIPT inbox-mark @ARGS` を実行する（以後、内容が変わるまで、`watch` で再通知しない）。
- `declined`（前に利用者が分類先を承認せず、それから内容が変わっていない資料）: 分類先を聞き直さない。
- `seen` が true の `ready`（前の実行で配置できなかった資料。`reason` に前の理由。例: `name_collision`）: `watch` の 2 回目以降の実行では、何もしない（知らせない）。手動の `organize` と `watch` の初回の実行では、下の手順で配置をやり直す。
- `ready`: 1 件ずつ、次の R1〜R6 を行う。

## ready の資料の扱い（R1〜R6）
R1〜R6 は、この節の中だけの番号。

### R1〜R4: 読んで、分類先を決める
- R1: 全文 `text_path`（`.vault-inbox/text/<id>.txt`）を読む（SKILL.md の「全文の読み方」に従う）。空なら `extract_failed`（空）として `inbox/` に残し、R6 へ。
- R2: 要約・日付（YYYY-MM-DD。文書内の日付、なければ今日）を作る。
- R3: 分類先を選ぶ。`project/<プロジェクト>/<分類>/…` か `shared/<種類>/<サブ>/…` の形で、`project/`・`shared/` の既存のフォルダを見て決める。階層は、`project/`・`shared/` を含めて 5 階層以内。
- R4: 既存に合うものがなければ、新しい分類先を AskUserQuestion の選択肢で提案する（推奨案を先頭に、ほかの案は 2 件まで、「配置しない」）。承認されなければ（「配置しない」を含む）、`inbox/` に残す（理由: 未承認）。R6 へ。

### R5: 配置する
- R5: 資料を分類先へ移して記録する。引数ファイルに `--name=<name>`・`--dest=<分類先>`・`--id=<id>`・`--hash=<hash>`・`--date=<日付>`・`--summary=<要約>` を書き、`SCRIPT place @ARGS` を実行する。返ったエラーごとに扱う。
   - `{"error": "name_collision"}`: 同名の資料が分類先にある。`inbox/` に残す（理由: name_collision）。R6 へ。
   - `{"error": "source_missing"}`: `inbox/` から消えている。知らせて次へ（記録しない）。
   - `{"error": "place_failed"}`: 分類先を作れない・資料を移せない（OS が受け付けない名前、同名のファイルが途中にある、など）。資料も記録も変わっていない。知らせて `inbox/` に残し、R6 へ（理由: failed）。
   - そのほかの想定しない失敗（上にないエラー、スクリプトの異常終了など）: 知らせて `inbox/` に残し、R6 へ（理由: failed）。
   - `{"error": "bad_destination"}`: 分類先の形が正しくない。正しい形（`project/<名前>` か `shared/<名前>` 以下。空・`.`・`..`・`.` で始まる名前、`\`、末尾の `/` は不可）の分類先を選び直して（既存に合うものがなければ R4 の提案に戻る）R5 をやり直す（記録しない）。選び直しは 2 回までとする。
     - 2 回選び直しても `bad_destination` が続くときは、知らせて `inbox/` に残し、R6 へ（理由: failed）。
   - `{"error": "bad_name"}`: 名前が正しくない。知らせて `inbox/` に残し、R6 へ（理由: bad_name）。

### R6: 配置しなかった資料を記録する
配置しなかった資料を、本当の理由で記録する（使われない全文のファイルは消える。以後、内容が変わるまで `seen` が true になり、`watch` の 2 回目以降は知らせない）。理由ごとに、引数ファイルに `--name=<name>`・`--hash=<hash>`・`--status=<理由>`・`--id=<id>` を書き、`SCRIPT inbox-mark @ARGS` を実行する。
- 分類先が承認されなかった（未承認）: `--status=declined` を書く（以後、内容が変わるまで `declined` として返り、聞き直さない）。
- name_collision: `--status=name_collision` を書く（手動の `organize` では、次も配置をやり直す。同名の資料がなくなっていれば配置される）。
- 空: `--status=extract_failed` を書く。
- `bad_name`: `--status=bad_name` を書く。
- 想定しない失敗: `--status=failed` を書く（`hash` は intake が返した値。記録しないと、`changed` が true のままになる）。

# Repo cleanup — 待執行計畫(2026-09-04)

原則:ops/ 只留必要操作紀錄,中間資料與可重算資料刪除;結論數字重構進文檔。
tools/ 只留可重用、不綁定特定 exhibition/series 的工具,按功能重命名。
凡 untracked 的刪除**不可從 git 恢復**——每項已確認有權威副本(鏈上 / IPFS pin / DB 可重匯)。

執行順序不可調換:**先 commit 要保留的 → 再刪 → 再改名 → 最後文檔重構**。
每個 Phase 結尾有驗證;驗證不過就停。

---

## Phase 0 · 開 branch、先保住 untracked 的保留項

```bash
cd /Users/yehboyang/status
git checkout -b chore/ops-tools-cleanup

# 這些現在是 untracked,必須先 commit(刪錯就找不回來):
git add ops/opensea-metadata-path/README.md \
        ops/opensea-metadata-path/collections_report.csv \
        ops/opensea-metadata-path/decentralized_collections.md \
        ops/opensea-metadata-path/ff_api_spotcheck.csv \
        ops/opensea-metadata-path/opensea_handoff.csv \
        ops/opensea-metadata-path/fix_unsupervised_collection_name.sql \
        ops/cdn-retirement-phase2/RUNBOOK-crystalline-base-uri.md \
        ops/cdn-retirement-phase2/step2/reference-fix-dirlisting.sql \
        tools/phase2-step3/gen-v3-sql.py \
        tools/pin-referenced/batch_pin.py \
        tools/opensea-collection-metadata-scan.py \
        tools/opensea-ff-api-spotcheck.py \
        ops/cdn-retirement-phase2/step0/base_uri_check.csv
git commit -m "ops/tools: commit untracked keepers before cleanup (opensea incident reports, crystalline runbook, v3 align + batch-pin tools, 182-row reference fix)"
```

注意:`tools/update-token-uri/v4-base-uri.config.json` 如果已填了 senderAccount,
**不要 commit**(帳號識別碼不進 git);crystalline tx 完成前也不要刪。

驗證:`git status --porcelain | grep '^??'` 剩下的全部應該是待刪項。

## Phase 1 · 大宗刪除(~29.6 GB)

```bash
# 1a. CDN mirror(29G;104/104 已 pin prod-02 並 byte-verified,step1/dir_cids.csv 是註冊表)
rm -rf phase2-mirror mirror-run.log

# 1b. 本地媒體 scratch(311M;MP4 在 CDN + IPFS 上,gitignore 註解即此意)
rm -rf hls

# 1c. step3 doc 樹(117M;全部已 pin,regen 工具可重生;本來就 gitignored)
rm -rf ops/cdn-retirement-phase2/step3/src \
       ops/cdn-retirement-phase2/step3/v3-src \
       ops/cdn-retirement-phase2/step3/v3-docs \
       ops/cdn-retirement-phase2/step3/crystalline-newdir

# 1d. v2-metadata-regen 中間產物(138M;原檔 gen.py 可重抓;
#     23 合約 rollout 的收據 = 鏈本身 + ops 文檔;done.txt 名單先抄進 STATUS.md 再刪)
rm -rf tools/v2-metadata-regen/src tools/v2-metadata-regen/runs tools/v2-metadata-regen/updates

# 1e. 雜項
find . -name __pycache__ -type d -prune -exec rm -rf {} +
find . -name .DS_Store -delete
rm -rf ops/3435-hls-fix/.omc ops/bitmark-cdn-retirement/.omc ops/cdn-retirement-phase2/.omc tools/.omc
```

## Phase 2 · ops/ 可重算資料刪除

```bash
P=ops/cdn-retirement-phase2

# 2a. pin-referenced 本輪中間檔(結論:76,448 root CIDs 全 present、全 pinned,寫進 STATUS.md)
git rm -q --cached $P/referenced_cids.txt 2>/dev/null; rm -f $P/referenced_refs.csv \
    $P/referenced_cids.txt $P/referenced_cids.txt.pinstatus.csv \
    $P/referenced_cids.txt.missing.txt $P/unpinned_v3docs.txt $P/unpinned_v3docs.txt.pinstatus.csv

# 2b. DB exports(可隨時重匯;要用時應重匯新的)
git rm -q $P/step2/v3_tokens_export.csv 2>/dev/null || rm -f $P/step2/v3_tokens_export.csv
git rm -q $P/step2/v4_tokens_export.csv $P/step2/crystalline_db_export.csv \
          $P/step2/truth_db_export.csv $P/step2/v4_overlay_export.csv
# export SQL 定義保留(step2/export-*.sql 是工具,不是資料)

# 2c. 已執行的 SQL 與 reference review 中間檔(generator + 輸入都保留)
rm -f $P/step3/v3-align.sql $P/step3/v3-align.skips.log \
      $P/step3/crystalline-align.sql $P/step3/crystalline-align.skips.log \
      $P/step2/reference-rows.sql $P/step2/reference-rows.log \
      $P/step2/reference_conflicts.csv $P/step2/reference_unmapped.csv
# 保留:step2/reference-fix-dirlisting.sql(182 筆修復決策紀錄,已在 Phase 0 commit)

# 2d. step0 大型 audit(鏈上可重算;小型 summary CSV 保留)
git rm -q $P/step0/population_tokens.csv $P/step0/v3_audit.csv \
          $P/step0/v4_audit_crystalline.csv $P/step0/v4_audit_truth.csv
rm -f $P/step0/v4_audit_crystalline.state.jsonl $P/step0/v4_audit_truth.state.jsonl
# 保留:population_by_contract.csv、base_uri_check.csv、v3_audit.contracts.csv、
#       excluded_tokens.csv、third_party.csv、cdn_dirs.csv、v3_tokens.csv(小)

# 2e. OpenSea delist scanner 狀態(報告結論已在 incident 文檔;scanner 保留可重掃)
git rm -q $P/opensea_delist_state.jsonl 2>/dev/null || rm -f $P/opensea_delist_state.jsonl
# opensea_delist_report.csv(840K)= 最終掃描報告 → 保留(15/5,930 + 11 背景 delist 的原始依據)

# 2f. 其他 ops 目錄
rm -rf ops/nonipfs-scan            # 只有 scanner state;結論 = status PR #10(5 件已修復驗證)
rm -f ops/opensea-metadata-path/scan_state.jsonl ops/opensea-metadata-path/scan.log \
      ops/opensea-metadata-path/spotcheck.log
git rm -q ops/bitmark-cdn-retirement/audit_2026-08-28.csv \
          ops/bitmark-cdn-retirement/v2_cdn_tokens_export_2026-08-28.csv
git rm -q ops/3435-hls-fix/pin_referenced_2026-08-28.csv     # 被 9/4 全綠 run 取代
# 保留:bitmark SUMMARY.md、plan.csv、result.csv、contracts.csv、verify notes、db/*.sql(小、決策紀錄)
# 保留:3435-hls-fix 其餘(migrated CSV、probe 紀錄、兩個 metadata-fix 目錄)

# 完成前 progress/config 狀態
rm -f tools/update-tezos-metadata/progress.json tools/update-token-uri/progress.json
```

驗證:`du -sh ops tools` 應約 `ops ≈ 25M`、`tools ≈ 50M`(node_modules 佔大頭)。

## Phase 3 · tools/ 重組重命名(git mv,保留歷史)

```bash
git mv tools/phase2-step0 tools/contract-audit
git mv tools/phase2-step1 tools/ipfs-mirror
git mv tools/v2-metadata-regen tools/metadata-regen
git mv tools/phase2-step3/v3-doc-regen.py  tools/metadata-regen/v3-doc-regen.py
git mv tools/phase2-step3/v4-dir-regen.py  tools/metadata-regen/v4-dir-regen.py
git mv tools/phase2-step3/verify-regen.py  tools/metadata-regen/verify-regen.py
git mv tools/phase2-step3/pin-docs.py      tools/metadata-regen/pin-docs.py

mkdir -p tools/db-align-sql
git mv tools/phase2-step3/gen-v4-sql.py        tools/db-align-sql/gen-v4-sql.py
git mv tools/phase2-step3/gen-v3-sql.py        tools/db-align-sql/gen-v3-sql.py
git mv tools/phase2-step2/gen-reference-sql.py tools/db-align-sql/gen-reference-sql.py
git mv tools/db-sql/gen-token-sql.py           tools/db-align-sql/gen-token-sql.py
git mv tools/bitmark-reference/gen-sql.py      tools/db-align-sql/gen-bitmark-reference-sql.py
# phase2-step2/README.md、phase2-step3/README.md 內容併入 db-align-sql/README.md 與 metadata-regen/README.md 後:
git rm -r tools/phase2-step2 tools/phase2-step3 tools/db-sql tools/bitmark-reference

mkdir -p tools/opensea
git mv tools/opensea-delist-scan.py              tools/opensea/delist-scan.py
git mv tools/opensea-collection-metadata-scan.py tools/opensea/collection-metadata-scan.py
git mv tools/opensea-ff-api-spotcheck.py         tools/opensea/ff-api-spotcheck.py

git mv tools/bitmark-pin tools/ipfs-pin
rm -f tools/ipfs-pin/pin.log tools/ipfs-pin/verify.log
git mv tools/pin_works.sh tools/ipfs-pin/pin-works.sh
git mv tools/pin_files.sh tools/ipfs-pin/pin-files.sh
# 不動:pin-referenced/ census-rescan/ archive-probe/ update-token-uri/
#       update-tezos-metadata/ build_archive_manifest.py check_claims.py contracts/
```

### 3b. 路徑引用修復(必做,不然文檔和腳本會斷)

```bash
grep -rn 'phase2-step[0-3]\|v2-metadata-regen\|bitmark-pin\|pin_works\|pin_files\|db-sql\|bitmark-reference\|opensea-delist-scan\|opensea-collection-metadata-scan\|opensea-ff-api-spotcheck' \
  --include='*.md' --include='*.py' --include='*.sh' --include='*.mjs' \
  ops tools README.md | grep -v node_modules
```

逐筆把舊路徑改成新路徑。重點檔案:`ops/cdn-retirement-phase2.md`、
`ops/cdn-retirement-phase2/HANDOFF-2026-09-04.md`(→ STATUS.md)、各工具 README、
`tools/metadata-regen/run-contracts.sh` 與 `make-configs.py`(內部相對路徑)、
`RUNBOOK-crystalline-base-uri.md`(引用 `tools/update-token-uri`,未改名,應不受影響——仍要確認)。

改完重跑上面的 grep,結果應為 0(文檔中「歷史敘述」裡的舊名可留,加註已改名)。

## Phase 4 · 文檔重構

1. **`ops/cdn-retirement-phase2/HANDOFF-2026-09-04.md` → 改寫成 `STATUS.md`**,內容:
   - V3 弧線閉環:2,341/2,341 chain txs(9/3)+ DB align 2,341/2,341(9/4,bare CID 形式,
     抽查 117 tokens / 224 media pairs 位元組全同)
   - Reference rows:+18,096 新 rows;182 筆壞 reference 修復(BOOM TOWN 8 個 dir CID 根層無
     index.html);1,857 conflicts 驗證良性不動;unmapped 1,632 無需動作(1,544 已有 ref、
     88 筆 imagedelivery.net 第三方)
   - pin-referenced 9/4:76,448 root CIDs 全 present、全數直接 pin(2,341 個 V3 新 doc 補直接
     pin,與 6 個 staging roots 解耦)
   - v2/goal-2 rollout 收據摘要:23 合約 done(名單已抄錄如下,原 runs/done.txt 可放心刪):
     `0x9294c5787f5bc7462e991fe8b6feac75f433ac39`
     `0x0a5c44da5f71b884c16a195cec304f47ac0233cf`
     `0x7a9ea7c036f6aab113e2563096ef1e0e56375a39`
     `0x63c8282c8705e7873b3302bd623b2bc8ebcdddd3`
     `0x1d5bdc75918600541c115b74b81a404c9e4af7d4`
     `0x513ac47320798fb6d74543242a9c0f686682998d`
     `0xadb387798599f5777cd0531c2ecb36007c1d1a51`
     `0x6e906b2e355294a6aecd6b4f75816eda9f703dda`
     `0xe5163c74ffe6563d75d750e5d767122500a1c337`
     `0xdb5f1adcffa1869b9711cbfbe3bf46cc5d5319e5`
     `0x29c9e04e05c5d261836e458bc5b779a7de3c58d6`
     `0x6dba130221a1c39f6623908a136976686050059a`
     `0x979316f5b3f3d8db956af519553c853525a5b1af`
     `0xaa02cc02f4531ee75d1b78cb5a155d4f3b54f830`
     `0xd8eed224e1b358fa6f7b167124c2c1afe42275b4`
     `0x28b51ba8b990c48cb22cb6ef0ad5415fdba5210c`
     `0x7a15b36cb834aea88553de69077d3777460d73ac`
     `0x8f30722dd16bd63cf2665c383c1aef5e307b0046`
     `0x6e82e4b398ca4137007ba69ddd6ff699334d13b5`
     `0x6003994adeca13407e8dbee808280cc3ef2ab820`
     `0xc4f0ee96676d3de800b9725eb628de1c5a0cbea1`
     `0x2a86c5466f088caebf94e071a77669bae371cd87`
     `0xe46a41b840176b62983fc71162dc9faeac4d9bcb`
   - 未完成(依序):census + status page 重建(目標 ETH dependent 11,389 → ~167)、
     #3435 checkpoint、unpin backlog(6 staging roots + 舊 V3 docs + crystalline 舊 dir +
     舊 HLS,census 確認後)、crystalline owner tx(等 key holder,RUNBOOK 有效)
   - crystalline DB align 已於 9/4 先行完成:9,048/9,048(0 skip,WHERE 釘舊 path)。
     **DB 目前領先鏈**,直到 owner tx 發出;若最終決定不發 tx,DB 必須 revert
     (gen-v4-sql 新舊 dir 對調重產即可)
   - OpenSea 硬規則不變:修復確認前不 refresh
2. `ops/cdn-retirement-phase2.md` 附上 9/4 進度一節 + 指向 STATUS.md;
   nonipfs-scan 結論一行併入(status PR #10,5 件 Art of Survival 縮圖 9/2 已修復驗證)。
3. `git rm ops/cdn-retirement-phase2/HANDOFF-2026-09-04.md`(內容已被 STATUS.md 取代)。

## Phase 5 · gitignore 收尾 + 驗證 + PR

```bash
# .gitignore:移除已不存在路徑的規則(hls/、step3 doc 樹等),加上:
#   .DS_Store
#   ops/**/*.state.jsonl
#   tools/**/progress.json

git status --porcelain          # 應只剩本次變更,無意外 untracked
make build && python3 tools/check_claims.py   # status page 建置不受影響(census data 未動)
du -sh .                        # 應 < 300M(原 ~30G)

git add -A
git commit -m "ops/tools cleanup: drop recomputable intermediates (29.6G), reorganize tools by function, refactor phase-2 status into STATUS.md"
git push -u origin chore/ops-tools-cleanup
gh pr create --title "ops/tools cleanup + phase-2 status refactor" --body "…(摘要 A-D)…"
```

---

## 明確不刪(理由備查)

| 檔案 | 理由 |
|---|---|
| `step1/dir_cids.csv` + `dir_sizes.csv` | 104 pin-unit 註冊表,unpin 階段唯一依據 |
| `step3/updates_0x*.csv`(6 檔) | 2,341 筆 old→new 映射;未來 unpin 舊 doc、audit 都要用 |
| `step3/staging_roots.csv`、`VERIFICATION.md`、`verify_v3.csv`、`regen_failures.csv` | 驗證與 staging 收據(小) |
| `step2/export-*.sql` | 重匯工具,不是資料 |
| `step2/reference-fix-dirlisting.sql` | 182 筆修復的完整決策紀錄 |
| `opensea_delist_report.csv` | 事件最終掃描報告(事件未結) |
| `ops/opensea-metadata-path/` 各報告 | 事件開放中,等 OpenSea 回覆 |
| `RUNBOOK-crystalline-base-uri.md` | tx 未發,進行中 |
| `tools/update-token-uri/v4-base-uri.config.json` | crystalline tx 完成前不動、不 commit |

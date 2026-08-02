---
name: reference-daytrade-brokers
description: 隔日沖分點註冊表 daytrade_brokers.py — 種子+多來源網路交叉比對+資料驅動偵測；敘事打⚡隔日沖標籤(不改外資/內資/散戶分類)
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

`daytrade_brokers.py`(repo root，2026-07-23 加）— 隔日沖/短線大戶分點註冊表。

## 緣起
使用者問「永豐金匯立是內資分點?」→ 9A81=本土永豐證券歸「內資」正確，但工具的「內資」是本土券商大雜燴(機構/大戶/隔日沖混在一起)。web 查證(股感等)公認隔日沖是**凱基松山、美林、摩根大通、國票敦北、富國建邦**等，永豐金匯立**不在**標準名單。需獨立隔日沖標記層。

## 三來源匯流 → `cache/daytrade_brokers.json`
1. **靜態種子** `_SEED`：凱基松山/城中/信義/台北、美林、摩根大通、國票敦北、富國建邦、元大土城永寧、統一士林、群益金鼎大安、中信忠孝
2. **多來源網路交叉比對** `update_from_web`：headless `claude -p --dangerously-skip-permissions` 搜多個台股財經來源、萃取各家隔日沖名單、算出現來源數。**≥2 來源=confirmed、單一=candidate**(不靠單一來源，使用者強調)
3. **資料驅動** `detect_from_data`/`update_from_data`：掃近 50 日 bsr_cache，指標 = **大買後隔日倒的比例**(cycles/big_buys)。大買=淨買≥當日量5%，隔日倒=次日賣≥前日買60%。**≥50%=confirmed、≥30%=candidate**，需≥5次大買事件。高分自動加、標 data+分數

## confidence：seed OR web≥2 OR data≥0.5 = confirmed；web=1 OR data 0.3-0.5 = candidate

## 整合
- `tw_chip_price.py`：`_daytrade_conf(code,name)` 查註冊表；行為序列每筆加 `daytrade`+`daytrade_conf`；`_fmt_series_line` 顯示 `⚡隔日沖`(confirmed)/`⚡隔日沖?`(candidate)。**額外標籤、不改 classify_broker_type 的外資/內資/散戶**(外資的美林/摩通也可同時是隔日沖)
- `chip_narrative.py` prompt：明文「⚡隔日沖分點的買盤≠內資機構認同、須點明短線」
- 週日 09:30 cron `--weekly`(data+web 都更)

## 效能教訓
bsr_cache `_prices.json` 有 per-price 明細太肥(50檔13.5s)→ 改讀 broker_monitor 的 plain `{code}_{date}.json`(只 per-broker net、小15倍、快17倍)，全掃1445檔~3.5分。同 (code,date) plain+prices 都在時 plain 優先

## 首次結果(2026-07-23)
data 偵測 28 分點：永豐萬盛0.8/元大竹科0.75/台新松德0.73/凱基城中0.6/凱基信義0.55 confirmed。乾淨重建後註冊表 50 分點/23 confirmed/22 有web來源(多來源交叉：凱基松山 6 來源、富邦建國純 web 發現)。**永豐匯立(9A81)未被偵測隔日沖**(大買後不常隔日倒)→ 與 web「不在公認名單」雙重印證。門檻先驗未回測

## 🚨 永豐金匯立(9A81)= 外資通路，非隔日沖也非內資(2026-07-24 更正)
web 深查：**永豐金證券 2025-10 併「台灣匯立證券」在原址設匯立分公司(9A81)**。台灣匯立=**里昂證券 CLSA**(外資，代表法人 CREDIT AGRICOLE SECURITIES ASIA B.V.)，本業服務外資法人台股經紀。→ 9A81 流量以外資法人為主，**掛永豐但實為外資通路**。`classify_broker_type` 已加 `_FOREIGN_CHANNEL_OVERRIDE=("匯立",)`，在本土前綴前先攔截判 foreign(commit 修正)；其他永豐分點仍 domestic。教訓：分點名稱開頭≠實際資金身分，併購/外資通路要 web 查證

相關：[[reference-chip-price-skill]]、[[reference-chip-cache-builder]]、[[reference-warrant-signal]]

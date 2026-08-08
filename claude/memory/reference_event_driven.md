---
name: reference-event-driven
description: 事件交易中樞 /event-trading — MOPS重訊分類+內部人設質;事件=事後標記/籌碼=事前偵測;分批擴充
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

事件交易(event-driven)中樞(2026-08-08 起,分批擴充):

- **理念**:MOPS 重大訊息是「法定確認」非「最早」(法定 2 日內、門檻實收資本20%/總資產10%/3億);純等公告無超額報酬,真 edge 在公告前的分點/集保籌碼痕跡 → **事件=事後標記、籌碼=事前偵測**
- **資料層** `tw_event_data.py`:TWSE OpenAPI 免認證乾淨 JSON —— 上市重訊 `opendata/t187ap04_L`、上櫃 `tpex.org.tw/openapi/v1/mopsfin_t187ap04_O`、內部人設質 `opendata/t187ap11_L`(月頻2.7萬筆)、鉅額 `BFIAUU`、月營收 `t187ap05_L`。⚠ OpenAPI 只回近期快照非歷史 → 每日抓存月檔累積去重(`cache/events/material_YYYYMM.json`)。MOPS 直接爬 `ajax_t05st01` 反爬,改用 OpenAPI
- **分類器** `classify()`:主旨→事件類型。陷阱:「合併」多半是「合併財務報告」要排除、「取得」含不動產/設備要排除只留取得股權(股份/普通股)
- **頁面** `/event-trading`(`event_hub.py`):roadmap 狀態表 + 各事件區塊(取得股權/公開收購/庫藏/現增減資/重大契約/內部人高設質 已上線,分點吸貨前兆旗艦開發中)
- **cron** 20:10 累積(不推播);MODULES 登錄表加一列即擴充新事件
- **Part4 roadmap**(全做分批):①分點吸貨前兆(旗艦,唯一跑在公告前)②內部人事前申報轉讓(法定提前3日,t187ap11只有月頻事後,事前申報待接)③公開收購(法定提前5日)④重大契約+法說會行事曆⑤現增減資CB
- 研究文件 `docs/strategies/event-driven.md`

相關:[[reference-disposal-rules]]、[[reference-chip-skill]]、[[reference-us-correlation]]、[[feedback-evidence-based]]

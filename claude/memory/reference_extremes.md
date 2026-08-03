---
name: reference-extremes
description: 一年高低極端榜 /extremes — 距最高點跌幅Top20 + 距最低點漲幅Top20；還原價全市場；20:00只更新頁面(推播2026-08-03取消)
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

一年高低極端榜(2026-07-28 加,`tw_extremes.py` · `/extremes`):

## 功能
全市場 4 位數個股(非 ETF)近一年:
- 📉 距最高點跌幅最大 Top20 =(現價−一年最高)/一年最高(≤0)
- 📈 距最低點漲幅最大 Top20 =(現價−一年最低)/一年最低(≥0)

## 資料/方法
- **還原價**(用戶指定,除息不失真):FinMind `TaiwanStockPriceAdj` **全市場單日查**(不給 data_id)→ ~2320 檔 4位數個股(涵蓋率≈未還原 2331,已排除權證;未還原 TaiwanStockPrice 全市場有 ~44k 列因含權證)。含還原 max/min/close。
- 一年高/低 = intraday 還原高/低的年度極值;現價 = 最新交易日還原收盤。
- 交易日曆:`_trading_dates` 取自 2330 一年日線(**不用 taiex.json,那只有63天**),回看 YEAR_DAYS=250(實際~243),需 ndays≥MIN_DAYS=60(排除剛上市)。
- **排除停牌/下市櫃**:`ACTIVE_WITHIN=2`,近 2 交易日無成交(last_idx<len-2)即剔除 —— 否則下市股「現價」是停牌前殘值造假跌幅(6883 微電能源停牌前1.74、從76.8「跌97%」)。全市場約排除 17 檔。n_delisted 回傳並顯示於頁面/報告。
- **名稱**:stock_names(TWSE ISIN)只有上市+上櫃 → 漏興櫃/全額交割;加 `_finmind_names`(TaiwanStockInfo ~3126檔,週快取 cache/finmind_names.json)fallback。
- 逐日全市場快取 `cache/year_prices/{date}.json`={stock_id:[max,min,close]}(首建~243次抓取數分鐘、之後每日增量)。結果 `cache/extremes_latest.json`。

## 教訓
- **日期一定顯示年份 YY/MM/DD**:漲幅榜大飆股的「低點」多在一年前(窗口起點),只印 MM/DD 會誤以為是近期→誤判資料錯(7610 低56.79@2025-07-25→收1495 = 真的漲26倍,非glitch)。跌幅榜也真實(6883 全額交割股1.74、從76.8跌97%)。
- stock_names 在 **concept_momentum/stock_names.py**(非 repo root);get_name(code,fallback='') 找不到回傳 code→顯示時 nm==code 則設 ""。

## 上線
- 網頁 `/extremes`(app.py route 讀 extremes_latest.json、無則即時算)+ 首頁 nav(concept_charts.py + dashboard.html)
- **每交易日 20:00 cron**(盤後還原價齊,is_trading_day 守門,帶 FINMIND_TOKEN)只更新 extremes_latest.json 供頁面用;**LINE 推播 2026-08-03 應用戶要求取消**(--line-to flag 保留可手動推)

## ⚠ LINE 每月額度
2026-07-28 推播遇 HTTP 429「reached your monthly limit」—— LINE Messaging API 免費方案每月訊息上限用完(影響所有推播工具,非本工具問題),需等月初重置或升級方案。

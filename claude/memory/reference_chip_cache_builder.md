---
name: reference-chip-cache-builder
description: chip_cache_builder.py 每日 20:30 動態分點快取建置器 — 族群∪強勢∪熱門∪watchlist，補 broker_monitor top-200 融資選股的缺口
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

`chip_cache_builder.py`（repo root，2026-07-21 加）— 每日分點 BSR 快取動態清單建置器。

## 為什麼
- 每日分點抓取原本只有兩處：`tw_chip_price_daily.sh`（08:50，固定只有 3491）+ `tw_broker_monitor.py --top-n 200`（18:00，選「融資餘額 Top 200」+ backfill_chip_price_history）
- **broker_monitor 選融資 Top200 會漏掉低融資的族群成分股 / 強勢股** — 實測族群∪強勢∪watch=209 檔，只 69 檔重疊到 Top200、140 檔沒被抓
- 6488 環球晶（上櫃）就是這樣一直停在 7/16 舊 cache（不在 Top200 + TPEx 爬蟲偶爾失敗）

## 做什麼
- 動態 union：族群成分股（concepts.json `themes.*.stocks`，~194）∪ 強勢股（近 5 日 second_wave_history candidates）∪ 推播 watchlist（chip_narrative_watchlist.json codes）∪ 當日成交金額熱門 top-N（排除 00 開頭 ETF）
- **跳過當日已快取**（`bsr_cache/{code}_{today}_prices.json` 存在就不抓）→ 只補 broker_monitor 沒抓的缺口
- 每檔 `tw_chip_price.analyze()` → 寫 bsr_cache + chip_price_history，逐日累積
- CLI：`--list-only`（只印 union）/`--hot-n N`（0=不加熱門）/`--max N`（union 上限）

## 排程與守門
- **20:30 平日 cron**（is_trading_day 守門），避開 18:00 broker_monitor（最長 105 分）
- 內建 `_wait_for_broker_monitor`：pgrep tw_broker_monitor 還在跑就等（最多 40 分）— TPEx Playwright 共用 Xvfb :99 不能並行
- 收盤後跑才對（成交金額熱門股需當日結算；盤中跑會誤抓前一交易日）

## 相關
- 分點限制：TWSE/TPEx 只當日、無歷史 API（見 [[reference-chip-episode-compare]]）；上櫃 TPEx 爬蟲要過 Cloudflare Turnstile、偶爾三次重試全失敗
- [[reference-chip-price-skill]]、[[reference-money-flow]]、[[reference-strategy-second-wave]]

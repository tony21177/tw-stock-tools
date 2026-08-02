---
name: feedback_margin_lookup_stale_price
description: tw_margin_lookup.py 的「現價」在收盤後可能是 stale 盤中值，引用前先用 FinMind 官方收盤校正
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---

`tw_margin_lookup.py` 每次都印 `[WARN] HTTP 404: query1.finance.yahoo.com/.../<code>.TW`，代表 Yahoo 價源掛了、它 fall back 到延遲源。**收盤後（13:30 後）跑出來的「現價」可能還是盤中 stale 值，不是當日官方收盤**。

範例教訓：2026-06-15 13:41 對 3491 跑 margin，現價顯示 $1,600 -5.33%；但官方收盤其實是 $1,555 -10.89%（差很多）。我直接引用 → 給了使用者錯的維持率（報 186%，實際 ~181%）。

**Why:** 維持率/距斷頭% 都是用現價算的，價錯則整串數字錯，回 Telegram 出去會誤導。

**How to apply:** chip / margin / chip-price 回覆引用「收盤價、漲跌%、維持率」前，先用 FinMind `TaiwanStockPrice`（start=end=當日）抓 official close 校正，尤其是收盤後第一個小時內。chip-price 工具用的 FinMind OHLC 是對的，可拿它的 close 當基準。相關：[[reference_chip_price_skill]] [[feedback_evidence_based]]

**2026-07-20 已修**：`tw_margin_lookup.py` 現價改用交易所 MIS 即時報價（`mis.twse.com.tw getStockInfo.jsp`，盤中即時、收盤後=官方收盤，來源標示在輸出「(交易所即時)」），Yahoo 降為備援。同日大改版：主指標改 **XQ/三竹口徑遞迴成本線**（全歷史、種子不敏感；`compute_recursive_cost` in tw_margin_monitor.py），維持率同時輸出五成(券商實務)/六成(法規上限)兩口徑區間 — 上櫃法規上限其實也是六成（金管會歷次令），但券商實務對上櫃/高價股常給五成，經 user 2026-07-20 指正確認。舊的「3個月FIFO視窗成本」降為第二段並明示非整體。

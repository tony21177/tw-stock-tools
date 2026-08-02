---
name: reference-chip-episode-compare
description: /chip-compare 兩波下殺籌碼對比頁（價格+借券SBL+外資累計+融資）；FinMind 資料集單位不一致教訓（融資=張、借券/法人=股）
metadata:
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

**⚠ 已下架(2026-08-01)**:用戶「兩波比對的刪掉 我沒在看了」——route/首頁按鈕/連結全移除,模組檔保留。FinMind 單位教訓仍有效。

單檔「兩波下殺」籌碼對比功能（2026-07-20 加，緣起 3491 昇達科 2025 vs 2026 兩波比對）：

- **入口**：`/chip-compare?code=XXXX`（預設比 2025 春 3-8月 vs 2026 5月至今）；nav 在籌碼價量頁列「📉 兩波對比」
- **模組**：`concept_momentum/chip_episode_compare.py`（抓 4 線 + 自動找低點拆下跌/築底段）；渲染在 `app.py` `_render_chip_compare_page` + `_episode_svg`（雙軸 SVG：價格左軸紅實線、借券賣出餘額右軸藍虛線、兩波窗口陰影）
- **4 線**：價格、借券賣出餘額(SBL, `SBLShortSalesCurrentDayBalance`)、外資累計淨額(三大法人 Foreign_Investor+Foreign_Dealer_Self)、融資餘額(`MarginPurchaseTodayBalance`)。快取 `cache/chip_episode/{code}_{start}_{end}_{today}.json` 1 天

## 🚨 FinMind 資料集單位不一致（2026-07-20 踩坑教訓）
- **融資 `TaiwanStockMarginPurchaseShortSale` 的 MarginPurchaseTodayBalance/Buy = 「張」**（raw 3279 = 3,279 張）→ **勿再 /1000**。曾誤把 3,279 張講成「3 張」給 user，被抓包
- 借券 `TaiwanDailyShortSaleBalances` SBL 餘額 = 「股」（raw 3,379,000 → /1000 = 3,379 張）
- 法人 `TaiwanStockInstitutionalInvestorsBuySell` buy/sell = 「股」→ /1000 換張
- 驗證單位的方法：拿 `tw_margin_lookup.py` 顯示值（張）對照 raw

## 資料限制
- **券商分點無歷史 API**（TWSE/TPEx 只當日）→ bsr_cache 最早 2026-05，2025 那波完全無分點細節。此頁只用官方借券+法人+融資
- 2026 仍進行中，低點=暫時低點；除息前借券有召回擾動（制度性 ≠ 空方撤退，見 [[feedback-borrow-pnl-check]]）

## 3491 兩波結論（供之後回訪驗證）
- 2025 春：下跌段無量陰跌（外資 -93 張、借券小增）→ 築底段外資狂賣 -3,141 張、借券暴增到 6,406 張高峰（空方低檔總攻押錯）→ 8 月軋空 V 轉
- 2026：下跌段外資主導殺盤（-3,753 張、借券 +2,237）→ 落底至今借券持平 3,600 張（空方克制、缺軋空柴火）
- 融資兩期都穩定（2025 ~4,700、2026 ~3,300 張，無斷頭潮）— 與 5347 跌停狂砍融資相反
- 待驗證：2026 若要複製 2025 V 轉，需見借券低檔再放大（軋空燃料）或外資分點轉持續買

相關：[[reference-chip-price-skill]]、[[feedback-borrow-pnl-check]]、[[reference-money-flow]]

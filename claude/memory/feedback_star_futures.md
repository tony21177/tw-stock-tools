---
name: feedback-star-futures
description: 全站標準:任何列股票的頁面/推播,有掛個股期貨的標的名稱一律標 ★
metadata:
  type: feedback
---

**有個股期的標的一律註記 ★**(用戶 2026-08-01「之後也要記得…檢查所有的」)。

**Why**:用戶做斷頭反彈/動能單常用個股期(槓桿做多/當沖),名單裡哪些有期貨是決策資訊。
**How to apply**:
- 共用 helper:`tw_stock_futures.fut_stock_set()`(TAIFEX 對照,263 檔,失敗回空集)。
- 新工具**在 name 產生源頭**加 `+ _fut_star(code)`(" ★"),page/推播/JSON 歷史一致帶星。
- 已覆蓋(2026-08-01 全站掃):margin-scan(★)/lin-matrix(📈)/stock-futures(本身)/extremes/foreign-cost/warrant-signal/lending_monitor(借券雷達+空頭撤退+heavy_cover)/second_wave/broker_monitor/limitup_signal(daily_screen 經由 screener/limitup 的名稱源頭已帶)。
- ⚠ 包裝 `_get_zh_name` 時注意各檔 fallback 簽名不同(lending 只吃一參數,要 try/except TypeError)。
相關:[[reference-stock-futures-ranking]]、[[feedback-change-sweep-all]]

---
name: reference-foreign-cost
description: 外資成本線 /foreign-cost — 遞迴成本(持股反推)篩現價110-140%;收斂度<0.3不列入;20:40 cron;已VWAP交叉驗證
metadata:
  type: reference
---

外資成本線 110-140% 篩選(2026-08-01,`tw_foreign_cost.py` · `/foreign-cost`):

## 口徑
- 遞迴成本(同融資成本線 XQ 口徑):今日成本=(昨成本×(持股−淨買)+還原收盤×淨買)÷持股;賣出以均價移除。種子=視窗首日收盤。
- 持股序列=**今日官方外資持股**(TaiwanStockShareholding.ForeignInvestmentShares)以每日買賣超**往回反推**(H_{t-1}=H_t−淨買_t;反推出負=資料不一致剔除)。
- 外資=Foreign_Investor+**Foreign_Dealer_Self**(FinMind TaiwanStockInstitutionalInvestorsBuySell,逐日全市場單日查,快取 cache/inst_day/ 250天,20:40 cron 自動增量)。
- **收斂度=一年累積買進÷現持股**——關鍵誠實開關:<0.3 不列入(台積電式萬年持股一年算不出真實成本);0.3-0.6 偏「近一年新倉成本」近似。
- 篩:現價/成本∈[110%,140%](外資獲利10-40%:有支撐未過熱)+持股≥5%股本+現價≥10元。

## 驗證(2026-07-31 首掃)
- 母體 856 檔、區間 125 檔。交叉驗證 vs 獨立買進量加權VWAP:矽力+2.7%/瑞昱−3.1%/樺漢−5.0% 吻合;健鼎−18%=遞迴正確語意(大賣後舊高成本批被均價移除,剩餘部位偏後期低接成本)。
- **已回測**(tw_foreign_cost_backtest.py,桶別 walk-forward):**單調梯度=外資獲利越多之後越強**。<100 被套區 H60 超額 −14.7% 全表最弱;110-140 **+3.6% 轉正**(絕對 69.4%/+28.7%)=有效;但 140-180 +13.2%、>180 +14.2% 更強 →「外資大賺會調節」不成立,**下限110(避開被套弱股)是 edge 主源、上限140 切掉最強群**。⚠ 一年動能市 regime、與價格動能高度相關。結論嵌頁面。

## 上線
- route /foreign-cost + NAV_LINKS「🌐 外資成本」;**20:40 cron**(is_trading_day 守門;需 extremes 20:00 先建當日 year_prices)重建 JSON 不推播。
- 近20日淨買欄:同區間內「外資還在買 vs 已調節」意義不同。
相關:[[reference-margin-scan]](遞迴成本線同款)、[[reference-sbl-surge-study]](inst_day/sbl_day 快取家族)

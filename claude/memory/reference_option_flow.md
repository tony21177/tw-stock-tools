---
name: reference-option-flow
description: 選擇權法人籌碼 /option-flow — TXO 自營收put轉多觀察訊號;tw_option_flow.py;15:10 cron 訊號觸發才推
metadata: 
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

選擇權法人籌碼(自營收 put)(2026-07-30 加,`tw_option_flow.py` · `/option-flow`):

## 邏輯(社群實戰口徑,用戶 LINE 群截圖)
TXO 自營商當 put「賣方」大量收權利金 = 造市/專業戶賭不跌、「沒事不會收那麼多」→ 轉多觀察。
- **淨收權利金 = short_deal_amount − long_deal_amount**(正=淨賣方收錢)。
- 訊號:🟢 自營put淨收 ≥1億 且 ≥近60交易日P90;🔴 淨買 ≤−1億 且 ≤P10(避險/偏空)。樣本<20日不出訊號。
- **已回測**(2026-07-30,`tw_option_flow_backtest.py`,2020-01~2026-07/1596日/26次🟢):**隔日無edge且低於基準**(H1 勝率50%/−0.38% vs 基準55.7%/+0.10%;gap 42%),訊號常在連續殺盤中隔天續殺(2024-08-02→隔日−8.35%)。**5~10日反彈傾向明顯**:H5 69.2%/+1.32%、H10 73.1%/+2.59%(基準59.7%/+0.52%、62.7%/+1.01%)→ 恐慌IV飆高權利金肥才收得到大錢,**訊號=恐慌/波動事件標記,非隔日方向**。⚠ 樣本叢集(2024-08連4天)+視窗重疊t高估;五分位無連續預測力;🔴大買put**不預測下跌**(之後反而偏漲,兩極端都只是波動事件影子)。結論嵌頁面(讀 option_flow_backtest.json)+推播文。

## 資料
- FinMind `TaiwanOptionInstitutionalInvestors` data_id=TXO:三大法人(自營商/投信/外資)×買權/賣權,欄 long/short_deal_volume/amount + long/short_open_interest_balance_volume/amount。**金額單位千元**(/1e5=億)。盤後(~15:00)公布。
- ⚠ **TAIFEX 慣例:夜盤(T-1 15:00→T 05:00)併入 T 日統計**(同 TaiwanFuturesDaily after_market 掛結束日),FinMind 無法拆日盤/夜盤。
- 加權 context:TaiwanStockPrice data_id=TAIEX spread/(close-spread)。

## 已驗證(2026-07-30 對群訊)
- 群訊「自營都 put 回收 2e」→ 資料:賣8.96−買7.26=**+1.70億**(口語進位,方向量級相符)。
- 「昨晚就收1e」→ 夜盤併入次日,+1.70 = 夜盤~1e + 日盤~0.7e 相容,無法單獨拆驗。
- 「早上就是轉多」→ 07-30 加權盤中最高 +2.8%(收 −0.26% 尾盤回落),早盤轉多屬實。
- 07-28 大跌日(−4.65%)自營put反向**淨買 −2.21億**(買保險),行為一致。
- P90(近60日)=0.51億 → +1.70億 = 3倍+,確實異常,首日訊號即觸發。

## 上線
- `/option-flow` route 讀 `cache/option_flow_latest.json` fallback build();首頁 nav 📊 選擇權法人。
- **每交易日 17:00 cron**(is_trading_day 守門):`--build --telegram`,只在訊號觸發時推睏霸數錢。⚠ **FinMind 同步 lag:TAIFEX 15:00 公布,FinMind 約 16~17 點才有當日**(07-31 實測 15:10 無/17:43 有);原 15:10 排程抓前日資料晚推一天 → 改 17:00 + 推播去重 `option_flow_pushed.json`(同訊號日推一次)。
- 頁面:訊號橫幅+近60日表(加權%/自營put/call、外資put/call 淨收、自營put未平倉淨)+白話 glossary。
- ⚠ caveat:自營含造市/避險腳非全方向單;call 方向解讀與 put 相反(收call=壓上檔);外資選擇權常搭期現貨對沖更難單獨解讀。
相關:[[reference-market-overnight]]、[[reference-margin-scan]]

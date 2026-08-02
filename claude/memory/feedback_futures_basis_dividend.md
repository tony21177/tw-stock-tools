---
name: feedback-futures-basis-dividend
description: 期貨基差策略必須用「除息調整後基差」，加權指數是價格指數、除權息旺季結構性逆價差非看空
metadata:
  node_type: memory
  type: feedback
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

`tw_futures_basis.py` 原本 `basis = 期貨 − 加權指數(TAIEX)` 沒扣除權息 → 誤判(2026-07-22 user 指正)。

**Why:** 加權指數(TAIEX)是**價格指數**，成分股除息當天機械性蒸發點數、不加回股利。台指期結算對此指數，故期貨合理價 ≈ 現貨 − 結算前未發放股利現值。**除權息旺季(6-9月、7-8月最兇)出現數百點「結構性逆價差」，純粹待除息、跟看空無關**。原工具三處判讀(三訊號 backwardation 腳、basis_extreme、directional_warn)全被污染、系統性偏空。

**How (2026-07-22 已修):**
- 新模組 `index_dividend_points.py`：`remaining_dividend_points(asof, settle, token, index_value)` → 結算前剩餘除息點數 D。公式 `Σ 指數×(該股市值/全市場市值)×(每股現金股利/股價)`
- **調整後基差 = 原始基差 + D**；三訊號逆價差腳/basis_extreme/directional_warn 全改用調整後基差
- 結算日 = 近月合約月第三個週三(`front_settlement`/`third_wednesday`)
- 資料源教訓：FinMind **全市場**股利查詢在此環境幾乎空(整年只回 2 筆)、逐檔查上千檔不現實 → **只查前 50 大權值股逐檔**(`TaiwanStockMarketValue` 取市值排序、指數極集中頭部覆蓋~75-85%)；輸出標覆蓋率%。TWSE 報酬指數/TAIFEX 理論價 API 都找不到乾淨來源
- 網頁/告警顯示：原始基差 + D + 覆蓋率 + 調整後基差；告警文案明講「旺季逆價差多為結構性、已用調整後判斷」

**注意**：sandbox 的未來除息資料稀(D 常算出很小)，真實環境台股 7-9 月除息 6 月股東會後就公告、D 會是幾百點。程式正確、magnitude 依資料完整度，覆蓋率% 誠實揭露。

相關：[[reference-money-flow]] [[feedback-borrow-pnl-check]]（同為除權息制度影響籌碼判讀）

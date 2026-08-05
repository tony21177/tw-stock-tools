---
name: reference-ftd
description: FTD 反彈確認日 /ftd — 歐尼爾 Follow-Through Day 狀態機(加權/S&P/Nasdaq);失敗率27.5/25.6/28.8%對上文獻;07:35+21:45 cron 新FTD才推
metadata: 
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

FTD 反彈確認日(2026-07-30 加,`tw_ftd.py` · `/ftd`,用戶截圖需求「開發成指標」):

## 規則(IBD 口徑,狀態機 detect())
uptrend →(收盤自 refpeak 回檔≥CORR_PCT=6%)→ correction →(創低後第一根收漲)→ rally Day1(防線 rally_low=修正低點)→(盤中破防線→回 correction 重數)→ 第≥MIN_DAY=4 天且單日漲≥FTD_PCT=1.7% 且量>前一日 → **FTD** → uptrend(refpeak 重設為 FTD 日收盤)。收復 refpeak 也可無 FTD 結束修正。
- 量:台股=**成交金額 Trading_money**(台股慣例)、美股=Yahoo volume。
- 失敗判定(evaluate):FTD 後 FAIL_WIN=25 交易日內 low<防線。

## 回測(內建,全歷史)
- 加權(2004起)51次 失敗率 **27.5%**;S&P(2001起)39次 **25.6%**;Nasdaq 66次 **28.8%** —— 正好落在文獻 25-30%,驗證演算法。
- FTD 後 20 日:加權 66.7%/+1.76%(對照 59.8%/+0.86%)、S&P 71.8%/+1.36%(對照 64.6%/+0.70%)、**Nasdaq 62.1%/+1.19% 無 edge**(對照 63.6%/+0.99%)。edge 溫和 → 主要價值=制度化再進場時機+明確停損(破防線=退出),非預測。
- 著名 FTD 都抓到:S&P 2022-10-21、2025-04-22、台股 2026-04-08(+4.61%/量1.53x,後60日+34.6%);Nasdaq 2026-06-18 FTD **失敗**接本波 7 月修正。
- 2026-07-30 當下:加權「修正中 距高點−16.4% 等Day1」、S&P 上升趨勢、Nasdaq 嘗試反彈第1天。

## 上線
- `/ftd` route 讀 `cache/ftd_latest.json` fallback build();首頁 nav 🚀 FTD 反彈確認。
- **cron 07:35(週一~六,抓隔夜美股 FTD)+ 21:45(週一~五,台股)**,無 is_trading_day 守門(資料驅動無害);**「最新資料日=FTD日」且未推過才推**:Telegram 睏霸數錢(-5229750819)+ **LINE 睏霸數錢(C96e49f2...)/田尾三人幫(Ca0735be...)**(`--line-to`,line_push 模組)。TG/LINE 任一成功即記去重檔 `cache/ftd_pushed.json` {index:date}(⚠ 表示另一通道失敗不重試 — LINE 額度用完月份 TG 照推、LINE 靜默跳過)。
- 搭配敘事:融資斷頭潮(多方投降)+自營收put(恐慌極值)標「底部區」,FTD 確認「反轉啟動」。
相關:[[reference-option-flow]]、[[reference-margin-scan]]、[[reference-market-overnight]]

2026-08-05 加櫃買指數(FinMind data_id=TPEx,2005 起,含當日與量):43 次 FTD、失敗率 23.3%(四指數最低)、H20 +2.02%/勝率 66.7% vs 基準 +0.71%/58.3%。頁面/推播自動涵蓋(INDICES 列表驅動)。

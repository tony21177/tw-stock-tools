---
name: reference-finmind-broker-history
description: FinMind 免費層有歷史分點!TaiwanStockTradingDailyReport 單日查回溯~2021,解鎖分點回測
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

**FinMind 免費層有歷史券商分點資料(2026-08-08 發現,先前誤判為付費)**

- **dataset**: `TaiwanStockTradingDailyReport`
- **參數**: `data_id`(股號)+ `start_date`=`end_date`(**單日查詢**,多日範圍會 400)+ token
- **欄位**: securities_trader(分點名)、securities_trader_id、price、buy、sell、stock_id、date
  = 分點 × 價位 × 買賣張數(與當日 BSR 同,但**有歷史**)
- **回溯**: ~2021 年中起(2021-06 無、2021-09 有),約 5 年
- **限制**: 免費層每小時 600 次請求;單日查 → 回測需 N事件×M日 大量呼叫,要快取+分批
- **先前踩坑**: 一開始用 `date` 參數→400,誤判「歷史分點=付費拿不到」寫進 docs/memory,
  2026-08-08 用 `start_date` 才成功。**教訓:FinMind 多數 dataset 用 start_date/end_date 非 date**

**解鎖**: 事件交易旗艦「分點吸貨前兆」原判無法回測→**重新可行**。
台虹驗證:5/1~7/3 各分點累積淨買,**兆豐南京 +6,802 張**(單一分點遠超他人),
跑在元太 6/30 加碼公告前 = 前兆訊號真實存在。全市場掃描+回測待建(見 docs/TODO.md 旗艦重啟)。

相關: [[reference-event-driven]]、[[reference-chip-skill]]、[[reference-finmind-migration]]

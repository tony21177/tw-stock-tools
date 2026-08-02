---
name: feedback-change-sweep-all
description: "每次改動後必須全面檢查其他所有同類位置,不能只修被回報的那一處"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

**每次改動都要檢查其他全部**(用戶 2026-08-01 明確要求「務必記住」)。

**Why**:同一 session 連續三次被用戶抓到「修了一處、同類問題留在別處」:
1. 深色主題只驗主工具頁 → 回測子頁仍舊淺色(用戶截圖抓到)
2. option-flow cron 15:10→17:00 改了排程 → 頁腳文案仍寫 15:10(全站掃描才抓到)
3. stock-futures 加「今日資料尚未公布(15:30後更新)」→ 沒考慮非交易日,週六顯示誤導文案(用戶抓到)

**How to apply**:
- 修任何 bug / 改任何機制前,先問「**同類問題還存在哪裡?**」,用 grep 全 repo 掃同 pattern(文案、class、時間、資料源呼叫),一次修完。
- 改 cron 時間 → 同步檢查:頁面文案、推播文、README、memory。
- 改共用 CSS/JS → 檢查全部 22+ 頁(自動化 curl/browse 掃,不能只看改的那頁)。
- 涉及「今日/日期」的文案 → 必考慮非交易日(週末/假日/颱風假),用 `is_trading_day.is_trading_day()`。
- 驗證手段:curl 全頁清單迴圈、browse 自動化檢查腳本(sticky/排序/顏色)、grep 文案 vs `crontab -l` 對照。
相關:[[reference-site-nav]]、[[feedback-update-readme-with-changes]]

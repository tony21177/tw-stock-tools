---
name: chip skill 21:30 disclaimer 要 check 當前時間
description: 跑 /chip 時若當前 Taipei 時間已過 21:30，借券賣出餘額是 final 數據，禁止再貼「21:30 後再驗證」的 disclaimer
type: feedback
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
`/chip` skill 紀律 4 提到「13:30 收盤後約 21:30 才公布完整借券賣出餘額」。但這只在當前時間 **< 21:30** 時才需要加 disclaimer。

**Why:** 我 2026-05-14 23:32 跑 6282 chip 時 paste 紀律式加了「等今晚 21:30 完整借券賣出餘額再給確定判讀」 — 但當下已 23:32，餘額早 finalize 2 小時。User 立刻糾正。

**How to apply:**
- 跑 `/chip` 報告或借券分析時，先 `date '+%H:%M'` 看當前小時
- 若 ≥ 21:30 (Taipei) → 直接寫「**5/X 餘額 N 張 final**」，不加 disclaimer
- 若 13:30 - 21:30 之間 → 加 disclaimer「等今晚 21:30 完整餘額」
- 若 < 13:30 → 還在盤中，餘額完全還沒出，只能用昨日 final + 今日借券交易/還券當粗略觀察

**通用原則：** 加 disclaimer 前先確認 disclaimer 的條件是否仍然成立。Paste 紀律不檢查時間就是 noise。

**歷史踩過點：**
- 2026-05-14 23:32 6282 chip 報告 multi-paragraph disclaimer that data 還沒 finalize — 事實是已 final 2 小時 (msg 1599 → user 1600 糾正)

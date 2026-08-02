---
name: 轉機接力策略 (Turnaround Relay)
description: tw_daily_screen.py 的兩層篩選策略代號 — Layer 1 turnaround_screener + Layer 2 ABCD 接力訊號。別名：轉機接力 / 轉機出量能 / TR 策略 / 兩層篩選
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
「**轉機接力**」(Turnaround Relay) — tw_daily_screen.py 盤前 07:30 cron 跑的兩層工作流。

策略別名 (使用者可能用任一稱呼):
- 「**轉機接力**」(Turnaround Relay) — 主要正式名
- 「**轉機出量能**」— 強調 Layer 1 轉機 + Layer 2 量能訊號 D
- 「TR 策略」/ 「兩層篩選」/ 「Layer 1+2」 — 簡稱

## 兩層架構

**Layer 1 — 轉機 (Turnaround)** — `tw_turnaround_screener.py`
基本面 + 技術面初篩：
- 毛利率 4Q 改善 (Δ ≥1.5pp，至少 2/3 QoQ ↑)
- 量能放大 (20d/60d ≥ 1.3x)
- 借券賣出餘額減少 (≤ 0.95)
- 收盤站上 MA60 + 季線曲率向上
- 排除任一季 GM < 0% (避開會計異常)

全市場 ~3000 檔 → 數檔到數十檔 candidates。產出 JSON 給 Layer 2。

**Layer 2 — 接力 (Relay)** — `tw_limitup_signal.py --codes-file <layer1.json>`
ABCD 四項接力型訊號 (各 1 分，滿分 4)：
- A 漲停接力 (近 3 日內漲幅 ≥+5%)
- B 借券回補 (SBL 餘額轉降)
- C 籌碼集中 (外資 ≥2 家 in top10 買超)
- D 量能蓄勢 (前日量 ≥ 20d 均量)

對 Layer 1 候選打分，分級顯示 (4/4 / 3/4 / 2/4 / ≤1/4)。

## Cron
```
30 7 * * 1-5 ... tw_daily_screen.py >> daily_screen.log 2>&1
```
盤前 07:30 跑 (Mon-Fri)，使用前一交易日收盤資料，9:00 開盤前布局用。

## 使用者怎麼跟我提到這個策略
- 「轉機接力」/ 「轉機出量能」/ 「Turnaround Relay」/ 「兩層篩選」/ 「TR 策略」 都指這套
- 「Layer 1」= turnaround_screener；「Layer 2」= ABCD 接力訊號
- 「後照鏡開車」= 用前一日 Layer 1+2 結果，看今日漲跌驗證 Layer 2 是否能 predict

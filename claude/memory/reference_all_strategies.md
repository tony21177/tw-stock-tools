---
name: tw_stock_tools 八大策略命名總表
description: 所有策略代號 + 對應工具 + 排程時間 + 用途。使用者用策略名稱 (e.g. 「跑借券雷達」「主力雷達結果如何」) 我都認得對應工具
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
tw_stock_tools 共 8 個有名稱的策略。使用者習慣用策略名稱而非檔名指稱：

## 🌅 盤前策略 (Pre-Market) — 找今日機會

### 轉機接力 (Turnaround Relay)
- 工具: `tw_daily_screen.py`
- 排程: 07:30 Mon-Fri
- 別名: 轉機接力 / 轉機出量能 / TR 策略 / 兩層篩選
- 內容: Layer 1 (turnaround_screener) → Layer 2 (ABCD 接力訊號) 兩層串接
- 詳見: `reference_strategy_turnaround_relay.md`

### 強勢股第二波 (Second Wave)
- 工具: `tw_second_wave.py`
- 排程: 07:40 Mon-Fri
- 內容: 強勢漲 → 1-2 週急殺 15-25% → 反彈啟動的純技術面 setup
- 詳見: `reference_strategy_second_wave.md`

## 🌙 盤後策略 (Post-Market) — 異常監控 + 動能變化

### 借券雷達 (SBL Radar)
- 工具: `tw_lending_monitor.py --mode lending`
- 排程: 16:00 Mon-Fri (收盤後)
- 內容: 抓議借量突增 (>5d 均量 ×2) 且利率異常 (<1% 或 >7%) 的個股
- 邏輯: 突發大量議借 + 極端利率 = 主力借券動作異常 (準備放空 or 套利)

### 族群熱力 (Theme Heatmap)
- 工具: `concept_momentum/run_daily.py`
- 排程: 17:00 Mon-Fri
- 內容:
  - 各概念族群動能評分 (≥70 強 / <30 弱)
  - 族群內 🟢 多 leaders + 🔴 空 laggards (配對交易)
  - Rerating 偵測 (β 調整後與其他概念相關性更高)
  - 業務轉型偵測 (新聞主題 ≠ 原概念)
  - 推送 Snapshot PNG + Trend PNG + 4 則文字摘要

### 主力雷達 (Smart-Money Radar)
- 工具: `tw_broker_monitor.py`
- 排程: 18:00 Mon-Fri
- 內容: 分點買賣超 + 融資連動分析 — 找出大分點長期買超 + 融資餘額同步上升的個股
- 邏輯: 雙確認 = 主力建倉而非短線炒作

### 空頭撤退 (Short Retreat)
- 工具: `tw_lending_monitor.py --mode sbl`
- 排程: 21:30 Mon-Fri (晚間)
- 內容: 借券賣出餘額單日減少 >10% 的個股
- 邏輯: 大量空單一夕回補 = 空方認賠 / 利空出盡 / 主力反手做多

## 🔍 CLI 策略 (使用者觸發)

### 沉睡巨人 (Sleeping Giants)
- 工具: `tw_dormant_giants.py`
- 內容: 曾 5x / 跌 ≥30% / 沉睡 ≥5y / 量縮震盪整理的標的
- 詳見: README 第 12 節

### 美台聯動 (US-TW Beta)
- 工具: `tw_us_correlation.py`
- 內容: 對指定美股 (NVDA/AVGO/AMD 等) 做 β 調整後的台股相關性掃描
- 預設: 全市場 --scan、240d 視窗、β 調整 (扣除 ^TWII / ^GSPC)

## 使用者怎麼跟我提到這些策略
- 直接用策略名: 「跑一下借券雷達」/「主力雷達結果如何」/「族群熱力今天」
- 用工具檔名: 「跑 lending_monitor」 — 也認得
- 「盤後跑的」= 借券雷達 / 族群熱力 / 主力雷達 / 空頭撤退 (4 個)
- 「盤前跑的」= 轉機接力 / 強勢股第二波 (2 個)

---
name: 策略歷史榜三分頁
description: concept_momentum dashboard 第 2-4 分頁，分別對應主力雷達歷史榜（10 日）、盤前訊號（TR + 2W，10 日）、借券動向（議借 + 撤退，5 日），自製功能於 2026-05-10 加入
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
dashboard 自上而下分頁順序：
1. 📊 大盤寬度 (active)
2. 🎯 主力雷達 ← NEW (10 日)
3. 🌅 盤前訊號 ← NEW (10 日)
4. 🌙 借券動向 ← NEW (5 日)
5. 🔥 今日快照
6. 📈 3 個月趨勢
7. 強勢族群領漲股
8. 完整排行

**檔案**:
- 主力雷達: `concept_momentum/broker_radar_history.py` + `_renderer.py`
- 盤前訊號: `concept_momentum/premarket_signals.py` + `_renderer.py`
- 借券動向: `concept_momentum/lending_history.py` + `_renderer.py`

**Cache** (gitignored, cron 累積，無 backfill):
- `cache/broker_radar_history/{date}.json` (cron 18:00)
- `cache/turnaround_relay_history/{date}.json` (cron 07:30)
- `cache/second_wave_history/{date}.json` (cron 07:40)
- `cache/lending_radar_history/{date}.json` (cron 16:00)
- `cache/short_retreat_history/{date}.json` (cron 21:30)

**主力雷達綜合分數**:
`score = consecutive_days × (log(top_broker_net_zhang + 1) + sqrt(margin_increase_zhang)) / 2`
負值 clip to 0；連續天數 = 0 → score = 0。

**設計文件**: `docs/superpowers/specs/2026-05-10-strategy-history-tabs-design.md`
**實作計畫**: `docs/superpowers/plans/2026-05-10-strategy-history-tabs.md`

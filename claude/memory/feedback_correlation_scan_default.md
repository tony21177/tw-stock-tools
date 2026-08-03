---
name: tw_us_correlation default to scan-all
description: When user asks to query a US ticker's TW correlation, default to full-market --scan mode, not concept-scoped
type: feedback
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
For TW–US correlation queries via `tw_us_correlation.py`, default to scanning ALL stocks across all concepts, not picking concepts thematically.

**Why:** When user asked "find TW stocks correlated with BE", I picked 4 energy/power-related concepts based on intuition and missed 高力 (which is in 液冷散熱 and turned out to be the highest after proper scan). User then said "之後我問你預設也是全掃" — they want full-market scan as default to avoid this bias.

**How to apply:**
- For any "查 X 美股 vs 台股" question, run with `--peer X` (no concept arg) to auto-enter scan mode.
- **Default to β-adjusted mode** (no `--raw` flag) — user explicitly requested this on 2026-04-29 after the 華新 vs AMD false-positive incident (raw +0.35 was just shared market β; β-adj +0.19 showed no real linkage). Only use `--raw` when user explicitly asks or for direct visual comparison.
- Default window is now 240 (changed from 60 on 2026-04-29 after the 台船 vs LITE noise incident: 60d +0.46 collapsed to 240d +0.14). Use 60-day only when explicitly comparing recent narrative or asked.
- When concepts are explicitly named (e.g. "ASIC vs AVGO"), concept-scoped query is still appropriate.

2026-08-03 起有網頁版 `/us-correlation`(首頁即時工具入口):概念模式即時算、全掃背景跑+快取 `cache/us_corr/`。CLI 與網頁預設都是 β 調整、全掃。

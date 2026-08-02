---
name: FinMind sponsor migration (2026-05-11)
description: 多個工具遷到 FinMind sponsor tier 的範圍 + 例外
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
2026-05-11 升級 FinMind sponsor tier 後完成的遷移：

**已遷移到 FinMind**:
- `tw_lending_lookup.py` 借入交易 + 借券賣出餘額（合併 TWSE + TPEx）
- `tw_lending_monitor.py` 兩個 mode (議借 + SBL)
- `tw_second_wave.py` 6-month 日線
- `tw_dormant_giants.py` 18-year 歷史
- `concept_momentum/data_fetcher.py` 概念股 3-month 日線
- `tw_limitup_signal.py` Yahoo fallback

**未遷移（FinMind 沒這 dataset）**:
- 還券明細 (TWSE t13sa870) — chip skill 紀律 6 retry 仍用
- 分點 BSR (TWSE + Playwright) — sponsor 無 per-broker dataset
- 美股部分 (tw_us_correlation) — FinMind 沒美股
- ^TWII 指數 (concept_momentum/fetch_taiex) — Yahoo 仍用，沒換的必要
- 新聞 (concept_momentum/news_fetcher) — FinMind 沒新聞

**新模組**: `finmind_client.py` (3 個 fetch 函式 + 1 個 whole-market helper)，retry 429 內建

**設計文件**: `docs/superpowers/specs/2026-05-11-finmind-migration-design.md`
**實作計畫**: `docs/superpowers/plans/2026-05-11-finmind-migration.md`

---
name: backtest-infra-2026-07
description: 2026-07-07 回測方法論翻修：backtest_lib/v2面板/6個回測頁/訊號成效追蹤器（週一 08:10 cron）
metadata: 
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

2026-07-07 完成回測方法論翻修（19 commits，詳見 README 各回測章節與 `docs/superpowers/plans/2026-07-06-strategy-backtest-improvements.md`）。

關鍵基礎設施：
- `backtest_lib.py`（成本 0.471%/bootstrap CI/dedup）+ `backtest_prices.py` v2 面板（`bt_cache/`，開盤+還原價+除息日）— 所有回測統一隔日開盤進場、日期配對基準、95% CI
- Dashboard 6 個回測/成效頁：`/second-wave-backtest` `/broker-radar-backtest` `/concept-backtest` `/turnaround-backtest` `/lending-backtest` `/signal-outcomes`，全部帶術語詞彙表（[[dashboard-glossary-required]]）
- **訊號成效追蹤器**：`concept_momentum/run_outcomes.py`，週一 08:10 cron 推 TG 週報，自動算 5 策略推播的 T+1/5/10/20 實際超額（後照鏡自動化）

回測結論（判讀時先看 README 對應章節的 CI）：主力雷達與空頭撤退在修正基準後無正 edge（空頭撤退前向超額為負、非轉多訊號）；議借 >7% 爆量是顯著看空確認；第二波僅 H=20 有相對 edge 且中位數為負（樂透型）；轉機接力 Layer 1 單獨無 edge，ABD<2 是顯著避開訊號；族群熱力 IC 顯著為真。

**2026-08-01 整合(v2,用戶更正)**:回測**搬到各策略區塊底部**(不是總覽頁):族群→首頁快照分頁底、第二波+轉機→盤前訊號分頁底、借券→借券動向分頁底、主力雷達→主力雷達分頁底、盤中模擬→/intraday-sim 頁尾;`<details>` 摺疊。實作 `_bt_fragment`+`_inject_tab`(dashboard route 動態注入)。**新回測上線=寫進對應策略區塊底部,不開新頁**。⚠ **注入片段 CSS 必須 `_scope_css` 加 #frag_id 前綴** —— 裸注入時回測 .pos{綠} 全域蓋掉首頁 .pos{紅},大盤寬度表紅綠反轉(踩過);:root 變數被 scope 失效→ _BT_VARS 全域補。舊網址 301→ /#bt-xxx。

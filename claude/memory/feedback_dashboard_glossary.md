---
name: dashboard-glossary-required
description: concept_momentum dashboard 所有網頁術語都必須有白話解釋（術語說明詞彙表）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

使用者要求：dashboard 網頁上用到的所有術語（統計、量化、籌碼）都要解釋意思，不能只丟術語。

**Why:** 使用者會直接看網頁判讀訊號/回測結果，術語不解釋等於資訊沒傳達；2026-07-06 執行回測改進計畫時使用者明確提出。

**How to apply:** `concept_momentum/app.py` 已有共用機制 — `_BACKTEST_GLOSSARY` dict（約 :3400）+ `_glossary_section(keys, title)` helper，頁尾渲染「📚 術語說明」表。任何新增/修改 dashboard 頁面時：新術語先加進 `_BACKTEST_GLOSSARY`（白話、含判讀方式與陷阱，風格仿既有 edge 條目），該頁的 `_glossary_section([...])` keys 補上；非回測頁（如訊號成效 tab）也要掛同一 helper。相關：[[reference_strategy_history_tabs]]

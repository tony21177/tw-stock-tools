# 🎫 權證量能觀察

| | |
|---|---|
| 頁面 | `/warrant-signal` |
| 模組 | `concept_momentum/warrant_flow.py` + `warrant_signal.py` + renderer |
| 排程 | 18:30 抓流量 + 18:40 推播 |
| 回測 | ⚠ 無 edge(頁面紅字揭露,當觀察工具) |
| 上線 | 2026-07-22 |

TWSE 六類權證爆量 × 買賣失衡偵測,標的股票聚合視角。
FinMind 無權證資料 → TWSE 直抓。詳細規則見頁面說明。

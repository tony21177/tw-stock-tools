---
name: tw_stock_tools 位置與用法
description: Taiwan stock lending/margin monitoring scripts — location, usage, scheduled jobs
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
User 在 2026-04-22/23 建置的台股借券 / 融資分析工具組。**使用前先讀 README** 取得完整用法。

**位置**: `~/project/tw_stock_tools/` (git repo, GitHub: https://github.com/tony21177/tw-stock-tools)

**腳本**:
- `tw_lending_monitor.py` — 借券議借異常 + 借券賣出餘額大幅減少（cron 排程推送 Telegram）
- `tw_lending_lookup.py` — 單檔借券狀況查詢（借券/還券/餘額逐筆明細）
- `tw_margin_monitor.py` — 全市場融資維持率預警（FIFO 加權成本）
- `tw_margin_lookup.py` — 單檔融資維持率估算
- `concept_momentum/` — 台股概念板塊動能分析（25 個熱門主題，FIFO+廣度+量能+RS 評分，每日 PNG + 互動 HTML + Telegram 推送）

**常用查詢**（user 常在 Telegram 請求）:
```bash
python3 ~/project/tw_stock_tools/tw_lending_lookup.py <代號>
FINMIND_TOKEN=... python3 ~/project/tw_stock_tools/tw_margin_lookup.py <代號>
```

**環境變數**:
- `TG_BOT_TOKEN` 存在 `~/.claude/channels/telegram/.env`
- `FINMIND_TOKEN` — user 的 FinMind 個人 token（免費版 600 req/hr 限制）

**Telegram 群組**: chat_id `-5229750819`（主要 user tony21177, user_id 919061490）

**Cron 排程**（已設定，週一到五）:
- 16:00 — 借券議借異常推送
- 17:00 — 概念動能 PNG + 文字摘要
- 21:30 — 借券賣出減少推送（餘額 21:00 後才公布）

**使用時注意**:
- 完整用法/邏輯/API 文件都在 `~/project/tw_stock_tools/README.md`，有疑問先讀它
- 股票中文名不要憑 Yahoo 英文名亂翻譯，要查證（如 6862 不是「三聯」而是「三集瑞-KY」）
- 借券賣出餘額（TWT93U）單位是股，程式內已 ÷1000 轉張，不要重複轉
- 融資成數用預設上市 60% / 上櫃 50%，特殊降成數個股未處理

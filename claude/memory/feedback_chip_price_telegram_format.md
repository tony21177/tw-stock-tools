---
name: chip-price 報告必須完整推送 4 段
description: 推送 chip-price 到 Telegram 時，禁止為了省篇幅刪除任何 section。tw_chip_price.py format_report 輸出 4 段都要保留並按相同順序排版。
type: feedback
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
當執行 `/chip-price` skill 或回應「XXXX 籌碼量價/價格」時，**Telegram 推送必須包含 tw_chip_price.py format_report 的完整 段**：

1. **Header** — 股票代號 + 名稱 + 日期 + OHLC + 漲跌% + 總量張數
2. **【🔥 Top 10 大單 cells】** — 個別 (broker × price × side × volume) 最大 10 筆，含 direction tag (⬇/⬆/↗/↘/△/▽)
3. **【⏰ 三階段分析】** — 每個價格區間 (早盤低 25% / 盤中 50% / 尾盤高 25%) 的 Top 3 買方主力 + Top 3 賣方主力
4. **【🎯 Top 5 買超分點價格指紋】** — 每個分點：avg、範圍、主買集中區 (adaptive threshold)、Top 3 買價、📈 主買區軌跡 (multi-day) 如有歷史
5. **【🎯 Top 5 賣超分點價格指紋】** — 同上但賣方
6. **【🌀 高賣低買 — 同分點兩面操作】** — 偵測「淨賣超但實際洗盤低接」型態的分點 (2026-05-13 加入)。對每個兩面操作分點計算 wash_score = (sell_avg - buy_avg) / day_range，正值代表 sold high / bought low。淨賣的高 wash_score 分點被標記「看似空、實際多」。
7. **【📅 連續性】** — 今日 Top 3 買賣方在近 N 日 Top 3 命中次數（如有歷史）

**Why:** 我 (Claude) 在 2026-05-13 推 3491 報告時偷懶把【⏰ 三階段分析】刪了，使用者立刻發現並要求補上。「分點 × 價格區間 × 買賣量」是 chip-price 的核心 insight，三階段是 day-zone 級的呈現，跟 Top 5 指紋 (per-broker 級) 互補，缺一不可。

**How to apply:**
- 推 chip-price 結果時把 stdout 完整貼進 Telegram reply
- 4 段順序固定：Top 10 cells → 三階段 → Top 5 買 → Top 5 賣 → 連續性
- 可以在最後加上「判讀」或評論，但不可刪除上述任何 section 來「節省篇幅」
- 如果單則訊息超 4000 字元被 Telegram 切，工具的 `_send_telegram` chunking 會自動分段；不要為此預先省略內容
- 不應該手動截斷或省略任何 broker 行 — 完整顯示所有 Top 5 + 三階段 Top 3

**例外**：若使用者明確要求「只看 X」(e.g., 「只看買超」/「只看 Top 5」)，才可裁切。預設一律完整推。

**踩過的歷史**：
- 2026-05-13 推 3491 報告 (msg 1508) 偷工省略三階段 → 立即被 user 抓出要求補。Memory + skill instruction 更新此規則。

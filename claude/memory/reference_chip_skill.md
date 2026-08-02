---
name: chip skill — 籌碼三線整合
description: 自製 user-level skill 在 ~/.claude/skills/chip/SKILL.md，台股單檔籌碼總覽（借券+分點+融資三線整合分析）。觸發條件 / 5 條判讀紀律 / 使用方式紀錄。
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
`/chip <code>` skill 在 `~/.claude/skills/chip/SKILL.md`，於 2026-05-08 建立。

**觸發條件：** 使用者說 `/chip XXXX`、「XXXX 籌碼狀況/三線/總覽」，或同時要看借券+分點+融資。單一維度查詢（如「XXXX 借券還券」）**不要**自動升級成 chip — 用 lending_lookup 即可。

**底層工具串接：**
- `tw_lending_lookup.py <code>` — 借券 + 還券明細 + 借券賣出餘額
- `tw_broker_lookup.py <code> --days 7` — 分點+融資連動
- BSR cache 直讀 (`bsr_cache/<code>_<date>.json`) — 補今日 Top N 賣超/買超分點
- `tw_margin_lookup.py <code>` — 融資餘額 + cohort 維持率
- 可選：concept_momentum/cache/results/latest.json 交叉族群

**內含 5 條判讀紀律（這是 skill 的核心價值）：**
1. 「借券交易」≠「借券賣出」— 早盤只看新借量易誤判（2313 5/7 教訓：早盤新借 2,000 張看似空襲，實際當日只賣 120 張，是空方大撤）
2. 老空頭回補（30+ 天 @1% 利率）= 利多；新空建倉（短天 @5%+）= 偏空
3. 三線方向必須一致才能下強訊號；衝突時下中性結論
4. 早盤（13:30 之前）不下確定結論，標註「等盤後完整數據」
5. 交易日感知 — 跳過六日 + 國定假日

**使用情境：** 之前 2026-05-06 ~ 5-7 對 2313 / 3491 的多次手動查詢（msg 1258/1262/1270/1279/1281/1286/1300）就是 chip skill 要自動化的目標流程。手動模式已踩過坑，skill 內紀律是基於那些教訓寫的。

**FinMind token 取法：** 不硬編碼，從 crontab 抓
```bash
crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/'
```

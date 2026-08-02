---
name: chip-price
description: 台股單檔日內籌碼 × 價格分析 — 取得當日 TWSE BSR (買賣日報表) 含每個分點在每個成交價的買賣量，列出 Top 10 大單 cells、三階段 (早盤/盤中/尾盤) 各方主力、Top 5 買賣超分點價格指紋。當使用者說 "/chip-price XXXX"、"XXXX 籌碼價格"、"XXXX 籌碼價量"、"XXXX 分點價格" 時觸發。
---

# Chip-Price — 台股單檔日內籌碼價格分析

## 觸發時機

- 使用者明確要 `/chip-price XXXX` 或「XXXX 籌碼價格 / 籌碼價量 / 分點價格」
- 使用者在 chip 分析後追問「價格分布」/「誰在哪個價位買」/「時間點大買賣」
- ⚠️ 不要跟 `/chip` (籌碼總覽) 混用 — `/chip` 是三線整合 (借券+分點+融資)，`/chip-price` 是當日 BSR 價格深度

## 執行流程

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_chip_price.py <code>
```

工具會自動：
1. 重抓 TWSE BSR (含 CAPTCHA, 5-15 秒)
2. 從 FinMind 抓 OHLC 取得當日價格區間
3. 計算 Top 10 cells、三階段、分點指紋
4. 輸出 Telegram 友善文字
5. 同步寫 cache 到 `bsr_cache/{code}_{date}_prices.json`

要推送 Telegram：加 `--telegram`，預設 chat_id = `-5229750819`。

要存結構化 JSON：加 `--json-out path.json`。

## ⚠️ Telegram 推送格式紀律 (2026-07-17 起完整 8 段)

當 Telegram chat 觸發此 skill 後，**reply 必須包含 format_report 的完整 8 段** —
禁止為節省篇幅省略其中任何一段。順序：

1. Header (代號 + 名稱 + 日期 + OHLC + 漲跌% + 總量)
2. 【🔥 Top 10 大單 cells】
3. 【⏰ 三階段分析】 ← **這段最容易被偷懶省略，但絕對不能省**
4. 【🎯 Top 5 買超分點價格指紋】 (含 adaptive 集中區 + Top 3 + 📈 軌跡)
5. 【🎯 Top 5 賣超分點價格指紋】 (同上但賣方)
6. 【🌀 高賣低買 — 同分點兩面操作】 (洗盤低接型態 + tick 時序分類)
7. 【🧭 分點行為 — 近N日連續買賣序列】 (外資/散戶指標/內資分組，每分點逐日淨買賣 + 買賣均價位階序列；2026-07-17 加入)
8. 【📅 連續性】 (若有歷史)

如果想加 commentary/判讀，**附加在末尾**，不要替代任何上面 section。

如果單則訊息 > 4000 字元，工具的 `_send_telegram` chunking 會自動切；
不要因為「太長」就預先省略內容。

## 6 大分析 Pattern (詳細描述見 README / memory `reference_chip_price_skill.md`)

| Pattern | 函數 | 輸入 | 揭露 |
|---------|------|------|------|
| **A. 集中度** | `broker_concentration_band` + `adaptive_concentration_band` | broker cells | 該分點 ≥X% volume 集中在哪窄區 (surgical vs averaging in) |
| **B. 跨日軌跡** | `broker_band_progression` | history JSON | 推升中 / 下移 / 盤整 跨日 band shift |
| **C. 高賣低買** | `broker_wash_candidates` | broker cells + day OHLC | 同分點 sell_avg > buy_avg 的兩面操作 |
| **D. 時序判定** | `build_price_to_time_map` + `broker_time_estimate` | tick data | ✅ 真洗盤低接 / ⚠ 追漲獲利出 / ⏱ 時序模糊 |
| **E. 真實時間階段** | `time_stage_breakdown` | rows + tick map | 09:00-10:08 / 10:08-12:22 / 12:22-13:30 各方主力 |
| **F. 連續性** | `_format_continuity` | history JSON | 今日 Top 3 在近 N 日命中次數 |
| **G. 行為序列** | `build_behavior_series` + `_format_behavior` | bsr_cache 近 N 日 (prices 優先, plain fallback) | 外資/散戶指標/內資分組，每分點逐日 淨買賣@均價位階 序列；**行為判讀由 Claude 看序列敘事，不是硬編碼標籤** |

## 🧭 行為序列判讀紀律 (2026-07-17)

工具只給序列（`07/15 +6.0k@83% | 07/16 -2.6k@48%`），**行為結論由你（Claude）從連續多天的序列推**，
推完必須用範例文那種敘事體呈現（外資動向 → 內資買賣分點逐個點名 → 散戶 → 結論），每個判斷都引序列證據：

- **隔日沖慣犯**：平常近乎零活動 → 某日大買（常 @90%+ 高位階）→ 隔日全倒。要看到**完整 買→倒 cycle**（如凱基信義 07/15 +2.2k@100% → 07/16 -2.1k），單日大賣不能斷言隔日沖
- **真累積 vs 沖來沖去**：看累計淨額 + 逐日方向一致性。台灣摩根 07/13 +5.6k、07/15 +6.1k、07/16 續買 = 波段累積；高盛逐日 ±3-6k 劇烈翻面、累計歸零 = swing/沖，兩者都「今日大買」但意義完全不同
- **低接 vs 追高**：@位階 (0%=當日最低價) — 連續多天低位階買 = 耐心低接；高位階大買隔天倒 = 隔日沖拉抬
- **外資分點 ≠ 外資自營**：含客戶委託單，慣例上當外資動向 proxy 但非嚴格等號
- **散戶指標**：永豐金總公司 + 國泰敦南 為經驗 proxy（大型網路下單通路），非官方定義
- **不可只挑符合敘事的分點**：外資有人低接就要同時看有沒有外資在倒（2026-07-16 華通：MS/瑞銀/美林低接 vs 高盛/摩通昨買今倒，外資合計仍賣超）
- **資料防呆**：休市日 stale cache（整日簽名與前日重複）工具已自動剔除（2026-07-10 事件：215/215 檔重複 07/09）；`—` = 該日無 cache，不是零買賣
- **plain cache 日沒有均價位階**（只有 prices.json 的日子有 @%）

## 輸出格式（範例）

```
2313 華通 籌碼價格分析 (2026/05/12)
開盤 $246.00 / 收盤 $260.00 / 高 $264.50 / 低 $246.00 (+5.69%)
總量 93,922 張

【🔥 Top 10 大單 cells (broker × price)】
1. 1480 美商高盛 @$246.50 買 8,200 張 ⬇ 早盤搶低
2. ...

【⏰ 三階段分析】
早盤 (低 25%: $246.00 ~ $250.63):
  🟢 買方主力: 高盛 +8,500張 / ...
  🔴 賣方主力: 國泰 -600張 / ...
盤中 (中 50%): ...
尾盤 (高 25%): ...

【🎯 Top 5 買超分點價格指紋】
...

【🎯 Top 5 賣超分點價格指紋】
...
```

## 判讀紀律

### ⚠️ 紀律 1：價格 ≠ 時間

BSR 沒有真正的時間戳。價格只是「時間的 proxy」：
- 開盤近低點 → 早盤
- 收盤近高點 → 尾盤
- 但若整日 V 型反轉，順序就會錯亂

→ 判讀時用「**$246-250 區買進**」這種**價位描述**，不要直接說「**早盤買進**」(可能誤)。

### ⚠️ 紀律 2：上市/上櫃覆蓋

- TWSE (上市) 100% 支援 per-price detail
- TPEx (上櫃) 目前不支援 per-price detail — fall back 到 `/chip` (aggregate-only)。工具會印 WARN 並 exit 1。

### ⚠️ 紀律 3：CAPTCHA 失敗

TWSE BSR 用 CAPTCHA 阻擋自動爬蟲。我們用 ddddocr 解，成功率 ~80%。如果 fetch 失敗：
- 工具會自動重試 10 次（換 CAPTCHA 圖）
- 若全部失敗，回傳 empty rows
- 重跑一次通常會成功

### ⚠️ 紀律 4：跟 /chip 的分工

- `/chip` = 三線整合（借券+分點 aggregate+融資）— 看「**今天是誰在主導**」
- `/chip-price` = 當日 BSR 價格深度 — 看「**主導者在哪個價位下手**」

兩個一起跑能拿到完整圖像。

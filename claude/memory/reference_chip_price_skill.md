---
name: /chip-price skill — 日內籌碼價格時間 3D 分析
description: 自製 user-level skill 在 ~/.claude/skills/chip-price/SKILL.md，台股單檔當日 (broker × price × time) 三維分析，含 8 段 report（2026-07-17 加分點行為分類）、7 個核心 pattern (集中區 / 軌跡 / 洗盤低接 / 時序判定 / 真實時間階段 / 連續性 / 行為分類)，tick-data 驅動。
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
`/chip-price XXXX` skill 在 `~/.claude/skills/chip-price/SKILL.md`，於 2026-05-13 建立並當日完整迭代成熟。

## 觸發條件
- `/chip-price XXXX`
- 「XXXX 籌碼價格」/「XXXX 籌碼價量」/「XXXX 分點價格」

## 跟 /chip 的分工
- `/chip` = 三線整合（借券+分點 aggregate+融資）— 看誰在主導
- `/chip-price` = 單日 broker × price × time 三維深度 — 看主導者**在哪個價位、哪個時間**下手

## 底層工具：`tw_chip_price.py`

### 核心 pipeline
1. `bsr_scraper.fetch_bsr_with_prices(code)` — TWSE BSR 解 CAPTCHA + per-(broker, price) rows
2. `tpex_scraper.fetch_tpex_with_prices(code)` — TPEx fallback (Playwright + Turnstile)
3. `infer_bsr_trading_date(stock_code, bsr_rows, target)` — 用 (volume, high, low) 匹配 FinMind 識別 BSR 實際交易日 (TWSE 沒給日期)
4. `get_ohlc(code, date)` — FinMind 拿當日 OHLC
5. `build_price_to_time_map(code, date)` — FinMind tick data → 每個價位的成交平均時刻
6. 分析函數 (見下方 6 大 pattern)
7. `format_report()` — Telegram 友善文字
8. `save_history()` — 自動寫 `chip_price_history/{code}_{date}.json` (10 天 rolling)

### 8 段 report (順序固定、不可省略；2026-07-17 起)
1. Header (代號 + 名稱 + 日期 + OHLC + 漲跌% + 總量)
2. 🔥 Top 10 大單 cells (broker × price × side)
3. ⏰ 三階段分析 (有 tick → 真實時間 / 無 tick → 價格 quartile)
4. 🎯 Top 5 買超分點價格指紋 (集中區 + Top 3 + 軌跡)
5. 🎯 Top 5 賣超分點價格指紋 (同上)
6. 🌀 高賣低買 — 同分點兩面操作 (洗盤低接 + 時序分類)
7. 🧭 分點行為 — 近N日連續買賣序列 (2026-07-17 加；同日應使用者要求從「制式規則標籤」改版成「多日序列 + Claude 敘事判讀」) — `build_behavior_series` + `_format_behavior`：今日 Top 8 買/賣方 + 達門檻外資/散戶指標分點，分 外資/散戶指標(永豐金+國泰敦南)/內資買方/賣方 四組，每分點列近 10 日逐日 `淨買賣@均價位階%` 序列 + 累計。**工具不下行為結論** — 隔日沖慣犯/真累積/沖來沖去/低接/追高由 Claude 看序列敘事（判讀紀律在 SKILL.md）。資料 bsr_cache prices 優先、plain fallback (無@%)；休市日 stale cache 自動剔除 (簽名與前日全同即丟，2026-07-10 事件 215/215 檔重複)。⚠ 外資分點含客戶委託非全自營；不可只挑符合敘事的分點（例 2026-07-16 華通：MS/瑞銀/美林低接 vs 高盛/摩通昨買今倒，外資合計仍賣超 -2,201 張）
8. 📅 連續性 (近 N 日 Top 3 命中)

## 7 大核心分析 Pattern

### A. 個別分點價帶集中度 `broker_concentration_band` + `adaptive_concentration_band`
- Sliding-window 找該分點 ≥X% volume 的最窄連續價格區間
- **Adaptive threshold**: 試 70% → 60% → 50% → 40% → 30%，取 band 寬 ≤ 25% of day range 的最高 threshold
- 高 % + 窄區間 = surgical (algorithm / 主力定點)
- 低 % + 寬區間 = averaging in / 散戶
- 例：花旗環球 $238-239.5 集中 72% (1.5 寬) = surgical；元大 $237.5-242 50% (4.5 寬) = 一般

### B. 跨日主買區軌跡 `broker_band_progression`
- 讀 `chip_price_history` 取該分點近 N 日集中區
- 比較 band low 趨勢：upward = **推升中**、downward = **下移**、unchanged = **盤整**
- 永豐金匯立 3491: 5/12 $1865 → 5/13 $1720 (下移) = chase momentum（⚠ 2026-07-24 更正：永豐金匯立 9A81 = 里昂 CLSA 外資通路、非散戶非內資，classify 已判 foreign，見 [[reference-daytrade-brokers]]）
- 富邦 3491: 5/12 $1765-1865 → 5/13 $1740-1755 (下移) = 持續分配 (selling into weakness)

### C. 同分點兩面操作 / 高賣低買 `broker_wash_candidates`
- 對兩邊都 ≥ 100 張的分點計算 `wash_score = (sell_avg - buy_avg) / day_range`
- 正值 = sell_avg 高於 buy_avg = 同分點內部 price spread
- **重點**：淨賣超但 wash_score > 0 → **看似空、實際多** (洗盤低接)
- Volume-weighted avg：`sell_avg = Σ(price × sell_shares) / Σ sell_shares` (同理 buy_avg)
- 例：富邦嘉義 2313 5/13 賣 342張 @$253.37 + 買 167張 @$243.49 → gap +$9.88 (46% range)，淨賣 -174 但實際在低接

### D. 時序方向判定 `build_price_to_time_map` + `broker_time_estimate`
- 用 FinMind `TaiwanStockPriceTick` (sponsor) 抓毫秒級 ticks (典型 20K+ 筆/檔/天)
- 為每個價位算 volume-weighted avg time (minutes from 09:00 open)
- 對 wash 分點計算 buy_time 跟 sell_time：
  - `buy_time - sell_time ≥ 30 min` → ✅ **真洗盤低接** (先賣後買)
  - `sell_time - buy_time ≥ 30 min` → ⚠ **追漲獲利出** (先買後賣)
  - 差 < 30 min → ⏱ **時序模糊**
- 例：2313 5/13 全部 5 個 wash candidate 都是真洗盤低接，賣 09:05-09:31 / 買 10:30-12:30 (1-3 小時 gap)

### E. 真實時間 三階段 `time_stage_breakdown`
- 用 price→time map bucket 每個 row 到 session 時間 quartile：
  - 前 25%: 09:00 ~ ~10:08
  - 中 50%: ~10:08 ~ ~12:22
  - 後 25%: ~12:22 ~ 13:30
- 比舊版「價格 quartile 當時間 proxy」可信
- **能偵測同分點日內方向反轉** (e.g. 元大 2313 5/13 早盤 -5,251 → 尾盤 +439，借勢洗盤)
- 無 tick 時 fallback 到 `stage_breakdown` (價格 quartile)

### F. 連續性 footer `_format_continuity`
- 今日 Top 3 買賣方在近 N 日歷史 Top 3 命中次數
- 高命中 = 持續主導 (信號可信)
- 0/N = broker 完全輪替（短線投機 / pattern reversal）
- 例：2313 5/12 vs 5/13 → 全部 0/1 (完全反轉 / 教科書誘多陷阱)

### G. 精準時序匹配 — 跨 cell 共聚 (2026-05-14 加入) `build_tick_index` + `match_broker_cells_consistent`
- 舊 `build_price_to_time_map` 給的是「該價位整體成交平均時間」，跟「該分點的成交時間」可能差很多 (實測 ground truth 差 42-61 分鐘)
- 新算法 4 層：
  1. `build_tick_index` — 從 FinMind tick 建 {price: [(time, vol_zhang), ...]} index
  2. `_cell_candidates` — 每個 BSR cell 枚舉候選 leading_block (vol ≥ 70% of cell, < cell)
  3. `match_broker_cells_consistent` — 跨 cell 共聚 (cross-cell consistency)：
     - anchor = 某 cell 有「明顯獨大」candidate (單一 / 1.3× / 同 vol 但 cluster span 5×)
     - centroid = anchor 時刻加權平均
     - ambiguous cell 取最接近 centroid 的 candidate
  4. fallback = weighted avg
- match_type confidence badge: ✅ exact / 🎯+ leading_block_consistent / 🎯 leading_block / 🔄 window / ≈ weighted
- 驗證：第一員林 5/14 \$50.30 / \$50.40 都 → ~11:36 (ground truth 11:35:38 / 11:36:12 ±1 分)
- 限制：當 broker 全部 cell 都無 anchor (同 vol 多 candidates 而 cluster span 差不多) → 退到 top vol candidate，可能誤判，此為公開資料極限

## 判讀紀律 (8 條)

1. **價格 ≠ 時間** (沒 tick 時)。價格 quartile 三階段是 proxy；V 型反轉日順序錯亂 → 有 tick data 時優先用真實時間階段。
2. **上市/上櫃** — TWSE + TPEx (Playwright) 都支援
3. **CAPTCHA 失敗時工具自動重試 10 次**
4. **/chip 跟 /chip-price 互補**，不要當成同一個工具
5. **交易日推斷**：信任 (volume, high, low) 匹配 FinMind，比 datetime.now() 或 FinMind latest 更可靠 (14:00-17:30 間 FinMind 領先 BSR 一天)
6. **wash_score > 0 不等於確定洗盤**：需要時序確認。沒 tick data 時只能說「淨賣但低接」，無法區分「真洗盤」vs「追漲後出」
7. **tick 時序估算是 proxy**：同價位多時段成交時 avg time 是中間值；30 min gap 閾值已涵蓋此噪音
8. **chip_price_history 需累積才能 surface 軌跡 + 連續性**：18:00 broker_monitor cron 開始累積 (2026-05-13 上線)，第 2 天起有資料

## 🤖 網頁 AI 行為敘事按鈕 (2026-07-17)

`/chip-price` 報告頁一鍵觸發：`concept_momentum/chip_narrative.py` 用本機 headless `claude -p` 產生敘事顯示在頁面。**兩檔模式**：完整版（預設主按鈕）= `--dangerously-skip-permissions` agentic，讀 chip/chip-price SKILL.md 後實跑三線整合（序列+借券/SBL+融資+除權息）交叉寫敘事，~5-10 分；快速版 = 純文字只餵序列，~1-2 分。檔案狀態機 `cache/chip_narrative/{code}_{date}[_full].json`(+.status)，同 (code,date,mode) 快取（每次產生=一次 Claude 用量，完整版較高），顯示優先完整版。API `POST/GET /api/chip-narrative?mode=full|quick`。CLI `python3 chip_narrative.py <code> <date> [--full] [--prompt-only]`。**快速版判讀紀律 prompt 內嵌在 chip_narrative.py — 改 SKILL.md 紀律時要同步改它**；完整版是叫 Claude 現場讀 SKILL.md，不用同步。full prompt 明文禁止推 TG/寫檔/重抓 BSR。

## Cache & 自動化

- **22:00 每日敘事 LINE 推播 cron** (2026-07-18 加) — `concept_momentum/chip_narrative_push.py` 讀 `chip_narrative_watchlist.json`（動態清單，預設 2313/3491/5347）逐檔抓 BSR→產完整版敘事（有快取重用）→推 LINE Messaging API（cron env `LINE_CHANNEL_TOKEN`+`LINE_USER_ID`；未設定時只產快取供網頁看）。22:00 = 借券餘額 21:30 公布後三線全齊。測試 `--dry-run`
- **`bsr_cache/{code}_{date}_prices.json`** — 原始 BSR (per-broker × price rows)，跟舊 aggregate cache 並存
- **`chip_price_history/{code}_{date}.json`** — 分析結果 (含 fingerprint + cells + stage + wash)，rolling 10 天，**未來再跑同檔可直接讀回前幾日的分析做推論**
- **08:50 daily cron** (`tw_chip_price_daily.sh`) — 跑 3491/2313/6282 (sequential，因 3491 是 TPEx Playwright)
- **18:00 broker_monitor cron** — 處理 top 200+ 檔，每檔同時 backfill 一份 chip_price_history (~15-20 min 額外時間)

## 設計文件與紀念碑
- 設計 spec: `docs/superpowers/specs/2026-05-13-chip-price-analysis-design.md`
- 實作 plan: `docs/superpowers/plans/2026-05-13-chip-price-analysis.md`
- 主要 commits: 5332917 (TPEx) / 935d984 (08:50 cron) / a7ef5db (broker_lookup A+B) / bf31416 (C+backfill) / 1ede92a (adaptive band) / 7abbb99 (wash detection) / 4c43fce (tick time-classification) / a097a24 (time-based 三階段)
- 2026-05-13 教科書案例: 2313 5/12 +5.69% (高盛 +11,837 教科書追進) → 5/13 -6.51% (高盛 -14,015 完全反轉)；3491 5/12 -5.36% (無法人承接) → 5/13 0.00% (無反彈確認)；6282 5/12 V 型反轉 (摩根大通 +3,738 確認底部)

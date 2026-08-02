# 訊號成效追蹤(run_outcomes)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 訊號成效追蹤 (`concept_momentum/run_outcomes.py`)

**自動後照鏡**：把 5 個推播策略每天存的 history JSON，自動配上 FinMind 還原價計算 T+1/5/10/20 的實際報酬 vs 大盤超額，每週一 08:10 推 Telegram 週報。

### date 正規化表（各策略 entry 口徑）

| 策略 dir | date 欄語意 | 進場日 (entry_date) 規則 |
|----------|------------|--------------------------|
| `turnaround_relay_history` | **資料日**（盤前資料，date = 前一交易日） | date 之後的**下一個**交易日（隔日開盤） |
| `second_wave_history` | **執行日**（盤前 07:40，date = 當日） | ≥ date 的**第一個**交易日（當日開盤） |
| `broker_radar_history` | 資料日（盤後 18:00） | date 之後的下一個交易日 |
| `lending_radar_history` | 資料日（盤後 16:00） | date 之後的下一個交易日 |
| `short_retreat_history` | 資料日（盤後 21:30） | date 之後的下一個交易日 |

### entry 口徑

- **進場價**：entry_date 的**還原開盤價**（TaiwanStockPriceAdj，開盤買最保守可實現口徑）
- **出場**：`trading_dates[entry_idx + h - 1]` 的還原收盤。h=1 = 進場當日開→收，h=5 ≈ 1 週

### T+h 慣例

```
h=1  : 進場日開盤 → 進場日收盤（持有當天）
h=5  : 進場日開盤 → 進場後第 5 個交易日收盤（~1 週）
h=10 : ~2 週
h=20 : ~1 個月
```

成效 = `(T+h 還原收 / entry 還原開 − 1) × 100 − TAIEX 同窗報酬`

### 產出

- `concept_momentum/cache/signal_outcomes.json`：全訊號報酬記錄 + 5 策略彙總 + TR abcd 分桶 + SW score 三分位 + **SW 分層標記分桶 (`sw_tier_buckets`，2026-07-08 加入)** + **SW 借券急跌標記分桶 (`sw_sbl_buckets`，2026-07-09 加入)**
- `concept_momentum/cache/outcomes_px/`：TAIEX + 個股還原價 快取（1 天 TTL）
- Dashboard：`/signal-outcomes` 獨立頁面（含 glossary，含 SW 分層標記分桶表 + SW 借券急跌標記分桶表）

**SW 分層標記分桶 (`sw_tier_buckets`)**：second_wave 訊號按 `tw_second_wave.py` 寫入的 `tier` 欄位（⭐/◐/▽）分桶，缺欄位（2026-07-08 前的舊訊號）歸入 `untagged` 桶，各桶算 h=1/5/10/20 的 n/exc_mean/win — 用來 forward-test 「子群分析」節的分層結論是否在新訊號上繼續成立。TG 週報僅當 ⭐ 或 ◐ 桶 T+5 樣本數 ≥5 才顯示分層行，避免初期噪音誤導。

**SW 借券急跌標記分桶 (`sw_sbl_buckets`)**：second_wave 訊號按 `tw_second_wave.py` 寫入的 `sbl_tag` 欄位（借↓/借↑/—）分桶，缺欄位（2026-07-09 前的舊訊號）歸入 `untagged` 桶，各桶算 h=1/5/10/20 的 n/exc_mean/win — 用來 forward-test 「籌碼確認（借券急跌變化）」節的結論是否在新訊號上繼續成立。TG 週報暫不加此桶（桶尚空，待累積樣本）。

### Cron

```
10 8 * * 1   # 每週一 08:10（交易日） → 計算 + TG 週報
```

### 使用

```bash
# 手動跑（不推 TG）
FINMIND_TOKEN=... python3 concept_momentum/run_outcomes.py

# 手動跑 + 推 TG
TG_BOT_TOKEN=... FINMIND_TOKEN=... python3 concept_momentum/run_outcomes.py --telegram
```

### 配額保護（FinMind）

- 空回應不寫 cache
- 每次 API 呼叫 sleep 0.03s
- 個股失敗 → skip + n_px_failed 計數
- >50% 個股失敗 → `[ABORT]` + sys.exit(3)

### 已知限制

- 回測窗口從 2026-04-01 起算（各 history dir 的最早落地日），樣本僅 ~60 天
- lending_radar 日均 50+ 檔訊號，個別 n 很大但訊號稀釋度也高
- 還原價使用 TaiwanStockPriceAdj，除權息前後日的跳空已消除，但盤中操作無法還原
- 今日訊號（entry_date = today）T+h 出場尚未發生，不計入統計

---

### 未來改進 (TODO / wishlist)

1. **分點行為 profile 跨檔聚合** — 同一 broker_id (e.g., 1480 高盛) 在 N 檔股票橫向看其行為一致性，建立 `broker_profile/{broker_id}.json` 持久檔案。可知該分點主要型態：定點主力 vs 散戶 vs algo vs 市場做市。當前每日分析孤立，不利累積長期 broker 知識。

2. **G 段時序匹配的 self-correction** — 提供使用者「**自助校準介面**」(web UI add-on)：使用者輸入自己實際 trade 時間 → 工具存進 `chip_price_truth/{date}/{broker}/{price}.json` → 隔日演算法在計算 anchor 時把這些 known-truth point 當高權重 anchor。
   現況：使用者只能口頭告訴我演算法錯了 → 我手動 reverse engineer 一次。理想：使用者點頁面輸入 → 工具下次自動更準。

3. **Tick-level broker assignment via 多日累積 pattern** — 同一個 broker 通常有特定下單規模 + 時段偏好。多日 ticks 累積後，可以 cluster：哪些 ticks 屬於同一個 trader/algo？這需要 unsupervised learning (clustering on volume, time-of-day, follow-up pattern) — 大工程，但能突破 BSR 無 timestamps 的根本限制。

4. **分點協同買進偵測 (broker chain coordination)** — 第一銀證在 6282 5/14 有 22 個分點同向買入 (合計 +180 張)，typical 主力借小分點群分散下單。可建立檢測：當同 broker prefix (e.g., 538*=第一銀，9800*=元大) 在同一檔多個分點同向總計超過閾值 → flag 為 coordinated。**已在 C 方案 D 點 backlog，今天還沒做**。

5. **TPEx tick data 支援** — 目前 `TaiwanStockPriceTick` FinMind sponsor 含 TPEx (3491 等)，需驗證 ticks 結構是否一樣，並調整 build_tick_index 處理上櫃格式差異 (如果有)。

6. **三階段分析跟 G 段 match_type 統一基底** — 三階段目前用 `price→time` weighted avg 來分配 row 到時段，跟新的 leading_block 邏輯不一致 (price→time 在 leading_block 看來會被拉偏)。應該讓三階段也用 G 段同樣的演算法，per-cell 確定時間後才 bucket。

7. **wash candidates 信心度標籤** — 現在只判 ✅ 真洗盤 / ⚠ 追漲後出 / ⏱ 時序模糊，沒給 confidence。可加入：buy_match_type 跟 sell_match_type 兩邊都 `leading_block_consistent` → 高信心；任一邊 `weighted` → 中信心。

8. **可指定多檔對照** — `/chip-price 2313+6282+3491` 同時查多檔，網頁顯示對比表 (e.g., 三檔的 高盛 today net 對比)。對「外資 同日反向 across 多檔」這種訊號有用。

9. **歷史 tick data 持久化** — FinMind sponsor 每次抓 tick 都拉一次 (~3 秒)。可以在 18:00 cron backfill 時也 cache `tick_cache/{code}_{date}.json`，讓 web UI 查歷史日子瞬間返回 (現在歷史日 backfill 沒 cache tick)。

10. **TLDR / executive summary section** — 報告 7 段內容資訊密度高，第一眼難消化。可加 section 0：「3 行判讀」(主力方向 / 量能信號 / wash 訊號)，給快速 decision-maker 用。剩 7 段詳細為 drill-down。

---

# 日內籌碼×價格(tw_chip_price /chip-price)

> ⚠ **每日 08:50 定時推播已取消(2026-08-03,用戶指示)**;手動 `/chip-price` 查詢與 `/chip` skill 照常可用,20:30 分點快取建置照跑。
>
> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## tw_chip_price.py — 單檔日內籌碼 × 價格 × 時間 三維分析 (CLI / Skill)

跟 `/chip` 不同 — `/chip-price` 專看單日 (broker × price × time) 三維分布，
偵測主力 footprint。Report 含 8 個 section：

1. **Header** — 代號 + 名稱 + 日期 + OHLC + 漲跌% + 總量
2. **🔥 Top 10 大單 cells** — 個別 (broker × price × side) 最大 10 筆，含 direction tag (⬇/⬆/↗/↘/△/▽)
3. **⏰ 三階段分析** — 早盤/盤中/尾盤各方主力 + 主賣方。**有 FinMind tick data 時用實際時間切分** (09:00-10:08 / 10:08-12:22 / 12:22-13:30)；無 tick 時 fallback 到價格 quartile heuristic
4. **🎯 Top 5 買超分點價格指紋** — 每分點 avg、範圍、**adaptive 主買集中區** (自動選最緊密 70%-30% threshold，cap 25% of day range)、Top 3 買價、**📈 主買區軌跡** (跨日 band 移動：推升中/下移/盤整)
5. **🎯 Top 5 賣超分點價格指紋** — 同上但賣方
6. **🌀 高賣低買 — 同分點兩面操作 (洗盤低接)** — 偵測同分點當日 sell_avg > buy_avg 模式 (wash_score)，**有 tick data 時加 buy_time/sell_time 時序分類**：✅ 真洗盤低接 (先賣後買) / ⚠ 追漲獲利出 (先買後賣) / ⏱ 時序模糊。**2026-05-15 補：每筆 wash 候選額外輸出主賣集中區 + 主買集中區 + Top 3 賣價 + Top 3 買價（與 Top 5 買超/賣超 section 對稱）**，方便對照同分點高賣 vs 低買的具體成交價分布。
7. **🧭 分點行為 — 近 N 日連續買賣序列** (2026-07-17 加) — 依券商名稱把今日重要分點（買賣超 Top 8 各方 + 所有達門檻的外資/散戶指標分點）分成 **🌏 外資 / 🏠 散戶指標 (永豐金、國泰敦南) / 🏦 內資買方/賣方** 四組，每個分點列出**近 10 日逐日淨買賣序列**：`07/15 +6.0k@83% | 07/16 -2.6k@48%`，`@%` = 當日買（賣）均價在該日高低區間的位階（0%=最低價、100%=最高價），另附今日淨額 + N 日累計。**刻意不做制式行為標籤** — 行為判讀（隔日沖慣犯 = 平日零活動→某日高位階大買→隔日全倒；真累積 = 逐日同向 + 累計墊高；沖來沖去 = 逐日劇烈翻面累計歸零）由分析者看序列敘事。資料來源：`bsr_cache/*_prices.json` 優先（有均價位階）、plain aggregate fallback（只有淨額）；**休市日 stale cache 自動剔除**（整日 (buy,sell) 簽名與前日完全重複即丟棄 — 2026-07-10 事件 215/215 檔重複 07/09 資料）。入選門檻 max(100 張, 當日總量 0.2%)。⚠ 外資分點含客戶委託、非全為外資自營；散戶指標為經驗 proxy；`—` = 該日無 cache 而非零買賣
8. **📅 連續性 (三層 view)** — (A) 今日 Top 3 買賣方在近 N 日 Top 3 命中次數；(B) **2026-05-15 加：近 N 日累積淨買/賣 Top 5**（不限今日 Top 3，捕捉「間歇式大量」主控分點；出現天數 ≤ 40% N 標記 ⚡ 間歇大量）；(C) **2026-05-15 加：今日 Top 3 之 N 日累積指紋**（顯示今日量 + 前 N 日累積 + 歷史最大日；若今日量 ≥ 60% 總量標記 burst）

### 核心分析 pattern (2026-05-13 完整版)

**A. 個別分點價帶集中度** (`broker_concentration_band`)
- Sliding-window 找該分點 ≥70% volume 的最窄連續價格區間
- Adaptive threshold：寬度 > 25% 全日 range 時降閾值，找出最緊密集中點
- 高 % + 窄區間 = surgical 操作（演算法/有目的的進場）
- 低 % + 寬區間 = 一般 averaging in（散戶 / 雜訊）

**B. 跨日主買區軌跡** (`broker_band_progression`)
- 讀 `chip_price_history/{code}_{date}.json` 取近 N 日該分點集中區
- 比較 band low 趨勢：upward = 推升、downward = 下移、unchanged = 盤整
- 推升中 = 主力連日加碼且接受更高成本
- 下移 = 平均成本下降，常見於 averaging-down 或 chase 反向動能

**C. 同分點兩面操作 / 高賣低買 + 低賣高買** (`broker_wash_candidates`, 2026-05-20 強化)
- `wash_score = (sell_avg - buy_avg) / day_range`
  - `> 0`: 高賣低買 (sell_avg > buy_avg) — 看似空但低接累積
  - `< 0`: 低賣高買 (sell_avg < buy_avg) — 認錯買回 / 慘賠加碼 (2026-05-20 加)
- **三層過濾防止 noise / lopsided 假 wash**：
  1. 兩邊都 ≥ 1 張 (1000股, 排除零股)
  2. 兩邊都 ≥ 1% × 當日總量 (排除單側 noise)
  3. min/max ratio ≥ 10% (排除 214買/1賣 這種一邊極小的偽 wash)
- **4 quadrant 時序判讀** (有 tick data 時):
  - 高賣低買 + 先賣後買 = ✅ 真洗盤低接 (bullish 主力低接)
  - 高賣低買 + 先買後賣 = ⚠ 追漲獲利出 (bearish 短線獲利)
  - 低賣高買 + 先賣後買 = ⚠ 認錯買回 (補回認賠或翻多)
  - 低賣高買 + 先買後賣 = ❌ 殺低出貨 (恐慌賣)
- 每筆 wash 候選額外輸出主賣集中區 + 主買集中區 + Top 3 賣價 + Top 3 買價

**D. 時序方向判定** (`build_price_to_time_map` + tick data)
- 用 FinMind `TaiwanStockPriceTick` (sponsor) 抓毫秒級 ticks
- 為每個價位算 volume-weighted avg time
- 對 wash 分點: buy_time - sell_time ≥ 30min → ✅ 真洗盤低接 / sell_time - buy_time ≥ 30min → ⚠ 追漲獲利出 / 否則 ⏱ 時序模糊

**E. 真實時間 三階段** (`time_stage_breakdown`)
- 用 price→time map 把每個 (broker, price, side) row bucket 到時間 quartile
- 前 25% / 中 50% / 後 25% session 時間 (09:00-10:08 / 10:08-12:22 / 12:22-13:30)
- 比舊版「價格 quartile 當時間 proxy」可信，能偵測**同分點日內方向反轉**
- e.g. 2313 5/13: 元大早盤 -5,251 → 尾盤 +439 (借勢洗盤)

**F. 連續性 footer** (`_format_continuity` + `_aggregate_broker_history`, 2026-05-15 重構)
- **Section A** 今日 Top 3 買賣方在近 N 日歷史 Top 3 命中次數
  - 高命中 = 持續主導 (信號可信)
  - 0/N = broker 完全輪替（短線投機 / pattern reversal）
  - 設計上 **excludes today**（hit rate 對照基準）
- **Section B** 近 N 日累積淨買/賣 Top 5（不限今日 Top 3）
  - 解決「間歇大量」盲點：broker 可能間隔幾天才買、但單日量很大也能主控走勢
  - 出現天數 ≤ 40% × N 標 ⚡ 間歇大量
  - 排序：純按 abs(total_net) 降序（規模優先）
  - **2026-05-15 改用 bsr_cache 全資料**（800+ 分點/日，非只 top 5），window 預設 5 日 = 1 trading week
  - Window 自動 include today (若今日 BSR 已公布)，視窗 label 顯示「近 5 日 (含今日 MM/DD)」或「近 N 日 (今日數據未公布)」
- **Section C** 今日 Top 3 之 N 日累積指紋
  - 每位今日 Top 3：顯示「今日量 + 前 N-1 日累積 = N 日累積 + 歷史最大日」
  - 若今日 |量| / N 日累積 ≥ 60% → 標 burst (今佔大半)
  - 區分「穩定大戶」(burst 0) vs 「今日 burst 進場」(burst 1)
  - 同樣讀 bsr_cache，能 catch chip_price_history top 5 漏掉的中量 broker
- **2026-05-19 加：1 月持有成本** (Section B + C)
  - 每行末加「(N日 均買成本 $XXX)」或「(N日 均賣價 $XXX)」
  - 從 bsr_cache `_prices.json` 算 volume-weighted avg price
  - 目標 20 trading days; 實際取在地可得天數 (透明標 "N日")
  - 主力 cost vs 現價 = 套牢 / 獲利狀態的快速判讀

**G. 分點 N 日時段 pattern** (`broker_timing_pattern`, 2026-05-20 加)
- 給定 (stock_code, broker_id, n_days=6) → 自動算每日該分點在「早盤 09:00-10:08 / 盤中 10:08-12:22 / 尾盤 12:22-13:30」三時段的買賣分布
- 配對當日 OHLC + 自動分類走勢「開高走低 / 開低走高 / 中性」
- 6 種行為標籤（依 dominant stage ≥50% + 淨方向）:
  - 🎯 尾盤低接型 (尾盤+淨買) — swing 部位
  - ⚠ 尾盤倒貨型 (尾盤+淨賣) — day-trade 結算
  - 🚀 早盤追擊型 (早盤+淨買) — 動能策略
  - 📉 早盤出貨型 (早盤+淨賣) — 停損 / 反向獲利
  - ⚖ 盤中布局/出貨型 (盤中) — TWAP/VWAP 演算法
  - 🔀 多時段混合操作 — 無明確 pattern
- 網頁版 broker drilldown 自動顯示, 每個標籤附可展開的詳細解讀 (專有名詞 + 推論依據 + 實務含意)

**G. 精準時序匹配 — 跨 cell 一致性** (`match_broker_cells_consistent`, 2026-05-14 加入)

舊的 `build_price_to_time_map` 只給「**該價位整體**」的成交平均時刻，跟「**該分點在該價位的成交**」可能差很多。實測 ground truth：第一員林 5/14 \$50.30 50 張實際 11:35:38 成交，舊算法估算 12:17 (差 42 分鐘)；\$50.40 30 張實際 11:36:12，估算 12:37 (差 61 分鐘)。

新算法 — 4 層 fallback：

1. **`build_tick_index(stock_code, date)`** — 從 FinMind 抓全部 ticks，建 `{price: [(time_min, vol_zhang), ...]}` index
2. **`_cell_candidates(cell_vol, tick_list)`** — 對每個 BSR cell，枚舉所有「leading_block」候選 tick：vol 至少佔 cell_vol 70%、嚴格小於 cell_vol (因為 BSR cell 通常是「主要 block + 小量 cleanup」組合，不是單一 tick 與 cell 完全相等)
3. **`match_broker_cells_consistent(cells, side, ticks_by_price)`** — 跨 cell 共聚 (cross-cell consistency)：
   - **Anchor**：某 cell 有「明顯獨大」的 candidate，視為 anchor (high confidence)
     - 單一 candidate
     - 或 top vol ≥ 1.3× second vol
     - 或同 vol 但 top cluster_span 寬 ≥ 5× → broker accumulation pattern
       (寬 cluster = 主 block + 鄰近 cleanup 小單，比 isolated single tick 更像同分點)
   - **Centroid**：所有 anchor 的 time 加權平均
   - **Pull**：模糊 cell (多候選 / 無明顯獨大) 取最接近 centroid 的 candidate
4. **Fallback** — 無 candidate 退到 `weighted` (price→time avg)

`match_type` 標籤透露信心度，UI 顯示為 confidence badge：
- ✅ `exact` — 單一 tick vol 完全等於 cell vol (僅小 cell)
- 🎯+ `leading_block_consistent` — leading block + cross-cell anchor 一致
- 🎯 `leading_block` — leading block 但無 anchor cross-check
- 🔄 `window` — sliding window 多 ticks 和等於 cell vol
- ≈ `weighted` — vol-weighted avg fallback

**8 個 ground truth case 驗證 (2026-05-14 ~ 2026-05-15)**：

| # | Stock | Cell | 用戶實際 | 演算法 | 狀態 |
|---|---|---|---|---|---|
| 1 | 3491 | 第一員林 \$50.30 52張 | 50張 block @ 11:35:38 + 2 cleanup | ~11:36 | ✅ |
| 2 | 3491 | 第一員林 \$50.40 34張 | 30張 block @ 11:36:12 + 4 cleanup | ~11:36 | ✅ |
| 3 | 3491 | 兆豐台南 \$50.60 37張 | 30張 main @ 10:32:50 + spread to 10:36 | ~10:33 | ✅ |
| 4 | 3491 | 兆豐台南 \$50.20  8張 | 4張 + 4×1張 burst @ 13:16:20-24 (4 sec) | ~11:58 (alt 13:14 ≈ truth) | ❌ |
| 5 | 2316 | 兆豐台南 \$137.50 17張 | 17張 全 in 集合競價 09:03:44.396 | ~09:03 | ✅ |
| 6 | 2316 | 兆豐台南 \$137.00 4張 | 4張 全 in 集合競價 09:03:44.396 | ~09:03 (primary) | ✅ |
| 7 | 2316 | 兆豐台南 \$136.00 15張 | 15張 集合競價 09:05:51.373 | ~09:02 (primary) | ⚠ 偏早 3 分 |
| 8 | 2316 | 兆豐台南 \$132.50 1張 | 1張 限價單 12:18:53.054 | ~10:47 ≈ | ❌ 差 91 分 |

**演算法原則 (從 case 1-3 推出)**：
- 真實 broker 主力 buy = lead block + cleanup small ticks 散布幾分鐘 (span 寬)
- 別人剛好同 vol 單一筆 = isolated single tick (span 窄)
- 當 2+ candidates 都 lead_pct >= 70% (都可疑)，**取 cluster_span_min DESC** 比 lead_vol DESC 準
- 例：兆豐台南 5/14 \$50.60 37 張 — 候選 35張@10:28 (span 3s = 別人) vs 30張@10:33 (span 4min = 用戶) → 取 span 寬 ✓

**Case 4 + 8 揭露的根本限制 — 三種 broker 填單 pattern**：

| Pattern | 結構 | Span | 識別性 |
|---|---|---|---|
| **A. 擴散填單** | lead block + cleanup 散在分鐘級 (case 1-3) | 寬 (10s-4min) | ✓ 用 span DESC 區分 |
| **B. 密集 burst** | lead block + cleanup 全在秒級 (case 4) | 窄 (3-10s) | ❌ 跟其他 broker 短 burst 無法區分 |
| **C. 集合競價** | 開盤前隊列 / 5-sec 撮合，所有單同一 ms 成交 (case 5-7) | 0 秒 | ✓ 一次大 tick anchor — 演算法表現完美 |

**Case 8 揭露 Pattern D — 「小張數 + 熱門價多 cluster」場景**：
- 1 張 限價單 @ \$132.50，但全日該價成交 121 ticks
- 121 ticks 分布在 09:07~09:09 (早盤殺低 65 ticks) + 12:18~12:44 (盤中 56 ticks) 兩個 cluster
- 演算法找不到 lead block (張數太小)，fallback 到 121 tick 加權平均 ~10:47
- 結果落在兩 cluster 中間「真空帶」，91 分鐘誤差，且無法靠 alternatives 修正（多 cluster 不在 alternatives 範圍）
- **本質**：1-3 張小單在 100+ tick 熱門價無法 anchor，公開資料無解

**同一個 broker 可能 cell A 用 Pattern A 填、cell B 用 Pattern B/D 填**（兆豐台南 5/14 \$50.60 用 A，\$50.20 用 B；5/15 \$137.5 用 C，\$132.5 用 D）。對 Pattern B/D 公開資料無解 — TWSE 沒提供 broker→tick mapping。

**對使用者的影響 / 補償**：
- 工具自動產生 `alternatives` (top 2 不同時間 candidates) 顯示在 UI
- Case 4 例: primary ~11:58 ❌，alt ~13:14 ✓ (跟 truth 13:16 只差 2 分)
- Case 8 例: primary ~10:47 ≈ — 多 cluster 場景已加上「multi_cluster」標記 + 各 cluster 時段顯示，使用者可從自己 trade 記憶選對 cluster
- 使用者用 alternatives + 自己 trade 記憶可以**手動修正** algorithm 的猜測

### 滾動歷史 archive (chip_price_history)

- 每次 `analyze()` 自動寫 `chip_price_history/{code}_{date}.json` (slim ~50-200 KB)
- Rolling 10 個交易日，自動 prune
- broker_monitor 18:00 cron 已加入 chip_price_history backfill — 每天**融資餘額 top 200** 檔自動累積
- **`chip_cache_builder.py`（20:30 cron，2026-07-21 加）** — broker_monitor 的 top-200 融資選股會漏掉低融資的族群/強勢股，本器補一份**動態 union**：族群成分股（concepts.json themes 全成員 ~194）∪ 強勢股候選（近 5 日 second_wave_history）∪ 推播 watchlist ∪ 當日成交金額熱門 top-N（排除 ETF）。**跳過當日已快取的**（不重抓 broker_monitor 已抓的）→ 只補缺口（實測 ~140 檔）。排 20:30 避開 18:00 broker_monitor 長工（最長 105 分），並內建 `pgrep tw_broker_monitor` 等待守門（TPEx Playwright 共用 Xvfb :99 不能並行）。用法 `--list-only`（只印清單）/`--hot-n N`（熱門股數，0=不加）/`--max N`（union 上限防爆時間）。目的：讓族群資金流/強勢股/熱門股每天有分點資料持續累積

### 使用
```bash
FINMIND_TOKEN=... python3 tw_chip_price.py 2313
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --telegram   # 推 TG
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --json-out out.json
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --date 20260512 --no-fetch  # cache only
```

### Skill 觸發
- `/chip-price 2313`
- "2313 籌碼價格" / "2313 分點價格" / "2313 籌碼量價"

### 自動 cron (固定觀察名單)

`tw_chip_price_daily.sh` — 每天 08:50 跑 3491/2313/6282 (sequential，因 3491 是 TPEx Playwright)

### Telegram 推送紀律

**完整 7 段缺一不可** — 禁止為節省篇幅省略任何 section。`_send_telegram` 自動 chunk >4000 字元訊息。
參見 `~/.claude/skills/chip-price/SKILL.md` 顯式紀律。

### 限制與 caveat
- **TWSE (上市)** 100% 支援；**TPEx (上櫃)** 透過 Playwright + Turnstile (~30 sec/檔，3491 已驗)
- **tick data 估算時序是 proxy**：weighted-avg 算法易被尾盤大量成交拉偏；G 段的精準匹配對「主 block + cleanup」cell 有效，但對全分散小單 (e.g., 全部 1-3 張零散買) 退回 weighted (`match_type=weighted`)
- **chip_price_history 需累積** — broker_monitor 18:00 cron 開始累積 (2026-05-13 上線)，**第 2 天起**有跨日軌跡，第 3+ 天起資料完整
- CAPTCHA 解析靠 ddddocr，成功率 ~80% (失敗自動重試 10 次)
- 主買區軌跡需 ≥ 1 日歷史；連續性 footer 需 ≥ 1 日歷史
- FinMind tick data 需 sponsor 版 (有 token 即可)；失敗時自動 fallback 到 price-quartile 三階段 + net-based wash 判讀
- **單一價位多 broker 同 vol coincidence** 在 G 段 cross-cell consistency 解之前是無解的：若該分點全部 cell 都缺乏 anchor (同 vol 多 candidates 而 cluster span 差不多)，centroid 無從建立 → 退回最大 vol candidate 當代表 (可能誤判)。這是公開資料 (BSR 沒分點 → tick mapping) 的根本上限
- **Pattern B 密集 burst 填單無解** (case 4: 兆豐台南 \$50.20 8張 4 秒內 4+1+1+1+1) — broker 用市價/積極限價單秒級填單，跟其他 broker 的短 burst 無法區分。Mitigation: 工具自動顯示 alternatives 讓使用者用自己 trade 記憶手動 override。詳見上面 4 case 表

## 欄位說明(2026-08-07 加)

頁面頂部可收合「📖 欄位完整說明」逐欄講意義+資料源+算法。核心限制:整頁建於 TWSE/TPEx BSR(分點×價位×張數,**無成交時間**),三階段/軌跡等時間欄位皆為「價格 quartile 當時間 proxy」;avg=成交值加權均價;集中區=自適應寬度密度聚類;BSR 約盤後 17:30 公布。

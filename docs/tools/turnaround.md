# 轉機接力(screener / limitup_signal / daily_screen)+ 族群熱力(concept_momentum)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 8. `tw_turnaround_screener.py` — Turnaround 篩選器

### 用途
找出同時滿足三條件的「基本面改善 + 量能進場 + 空方撤退」標的：
- 毛利率近 4 季向上（基本面改善）
- 量能放大（資金開始流入）
- 借券賣出餘額減少（空方回補）

對應的市場 narrative：「公司轉好 + 法人買進 + 之前空它的人開始認輸」 — 經典 turnaround setup。

### 過濾條件（可調）
| 條件 | 預設值 | 意義 |
|------|--------|------|
| `--gm-pp` | 1.5 | GM_Q-0 - GM_Q-3 ≥ N pp（4 季累積增幅） |
| `--gm-qoq` | 2 | 4 季中至少 N 次 QoQ 增長 |
| (固定) | 4 季 GM 均 ≥ 0% | 排除任一季 GM < 0% 的股票（避免處分損失/單季虧損等會計異常造成的假信號，例如 2527 宏璟 Q-2 GM -482%） |
| `--vol-ratio` | 1.3 | 近 20 日均量 / 近 60 日均量 ≥ N |
| `--sbl-decline` | 0.95 | 近 10 日借券賣出餘額均 / 前 30 日均 ≤ N |
| (固定) | 收盤 ≥ MA60 | 收盤價站上季線（quarterly MA） |
| `--ma-accel-days` | 5 | 曲率比較窗口（近 5td 斜率 vs 前 5td 斜率） |
| `--ma-curv-ratio` | 0.5 | 曲率寬鬆度。slope_recent ≥ ratio × slope_earlier。1.0=嚴格加速、0.5=允許動能減半（預設）、0.0=只要求斜率為正 |

### 資料來源
| 指標 | 來源 |
|------|------|
| 季毛利率 | FinMind `TaiwanStockFinancialStatements`（Revenue + GrossProfit） |
| 量能 | Yahoo Finance（6mo 日線） |
| 借券賣出餘額 | FinMind `TaiwanDailyShortSaleBalances` 的 `SBLShortSalesCurrentDayBalance` |
| 借券交易量（proxy） | FinMind `TaiwanStockSecuritiesLending` aggregated daily |

注意：
- 融券餘額（`MarginShortSalesCurrentDayBalance`）也會抓但只顯示作參考，不納入過濾。設計上「借券賣出餘額」是法人空方主戰場，融券是散戶/投機部位，兩者邏輯不同。
- 借券餘額（gross outstanding）TWSE 不公開逐日資料，本工具改抓「借券交易量」作為 proxy 顯示。借券賣出餘額減少 + 借券交易量也減少 = 空方收手；借券賣出餘額減少但借券交易量增加 = 法人換手，需警覺。
- **GM 快取 TTL**：季毛利率快取在財報公告死線前後窗口（3/25–4/10、5/5–5/25、8/5–8/25、11/5–11/25）內採 3 天 TTL（快速同步新季報），其餘平時 21 天 TTL。原先 30 日統一快取會導致新季報最多晚 30 天才生效。

### 使用方式
```bash
# 預設掃描全市場 TWSE + TPEx 4 位數普通股（~3000 檔，首跑 ~2-4 小時，後續快取後 ~30 分）
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py

# 只掃 concepts.json (~190 檔，快很多，10-15 分)
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py --universe concepts

# 調整門檻
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py \
  --gm-pp 2.0 --vol-ratio 1.5 --sbl-decline 0.90

# 指定股票
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py \
  --universe 2330,2454,3491

# 用 FinMind token 加速（避免 free tier rate limit）
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py \
  --token $FINMIND_TOKEN
```

### Universe 選項
- `--universe all`（預設）：FinMind TaiwanStockInfo 撈全 TWSE + TPEx，篩 4 位數純數字代號（避開 ETF 0050、REITs 01001T、權證等），約 3000 檔。Universe 列表 cache 7 天。
- `--universe concepts`：concepts.json 內 ~190 檔（已分類在主題板塊，掃描較快）
- `--universe 2330,2454,3491`：指定股票測試

### 輸出
1. 表格列出通過所有 3 條件的標的（按綜合分數排序）
2. 每檔詳細：
   - 4 季毛利率 + Δpp + QoQ 次數
   - 量能 20d / 60d
   - 借券賣出 10d 均 vs 前 30d 均
   - （參考）融券同期變化

### 限制
- FinMind free tier 有 rate limit（600/小時），全市場掃約 8-15 分鐘；用 token 可加速
- 季財報有 lag：Q1 財報通常 5 月公告，Q4 財報 3-4 月，掃出來的 GM 可能不是即時最新季
- SBL 餘額只反映「沒回補的部分」，不直接等於「主力多空態度」 — 配合分點/法人籌碼一起看更準
- 預設 universe 是 concepts.json (~190 檔)；`--universe all` 全市場尚未實作

### 實例（2026-04-29 跑出 6 檔，加上 D 過濾後）
3105 穩懋 GM 16.7→31.8% / Vol 1.30x / SBL -10.9% / MA60 +42%（趨勢最強）
4576 大銀微 GM 35.8→38.4% / Vol 1.64x / SBL -47.5% / MA60 +46%（趨勢強，融券 +246% 散戶反向）
3491 昇達科 GM 50.6→58.6% / Vol 1.55x / SBL -16.2% / MA60 +7%（多頭剛確立）
6173 信昌電 GM 22.3→26.8% / Vol 1.62x / SBL -26.3% / MA60 +22%
3406 玉晶光 GM 30.9→34.3% / Vol 1.56x / SBL -31.3% / MA60 +13%（融券 -85% 最乾淨）
6166 凌華 GM 34.5→36.7% / Vol 1.96x / SBL -5.7% / MA60 +16%

被 D 過濾掉：2314 台揚（GM 剛轉正但價格未站上季線）

---

## 9. `tw_limitup_signal.py` — ABCD 接力型訊號分析

### 用途
對輸入的股票清單做 ABCD 四面向訊號評分。兩種使用模式：

**模式 1: Standalone 漲停掃描**
無 `--codes` 參數時，掃當日全市場漲停股 (≥9.5%)，回看前一交易日訊號。
適合事後分析「今日漲停的前日訊號是否齊備」。

**模式 2: Layer 2 — 接力型過濾 (cron 用)**
指定 `--codes` 或 `--codes-file` 時，對提供的清單 (通常來自 Layer 1 turnaround screener) 做 ABCD 評分，
找出 Layer 1 候選中「明日續攻機率高」的子集。

設計動機：4576 大銀微系統 (2026-04-30 漲停) 的事後回顧顯示前一日已有三項一致訊號
(漲停接力 + 借券回補 + 外資集中買進)，可被前瞻識別。本工具將該模板抽象為可複用的 ABCD 訊號層。

### 盤前/盤後 mode 語意（2026-07 新增）

`--mode {auto|premarket|postclose}`（預設 auto）：

| mode | 使用情境 | anchor 位置 | A/D 視窗說明 |
|------|----------|-------------|--------------|
| **postclose** | standalone 漲停掃描 (`--date`) | `px[-1]` = 漲停日本身 | A 看 px[-2]/[-3]/[-4]；D 前日 = px[-2] |
| **premarket** | Layer 2 盤前 (`--codes/--codes-file`，07:30 cron) | `len(px)` (「今天」尚未發生) | A 看 px[-1]/[-2]/[-3]；D 前日 = px[-1] |
| auto | 有 `--codes/--codes-file` → premarket；否則 → postclose | — | — |

`tw_daily_screen.py` 的 cmd2 傳 `--mode premarket`（顯式，不靠 auto）。

⚠ **2026-07 之後的 `abcd_score` 與之前版本不可直接比較**：盤前模式 A/D 現在納入最新一根K棒（昨日），舊版漏看該K棒，分數基準不同。

### 四項訊號（各 1 分，滿分 4）
| 訊號 | 條件 | 含義 |
|------|------|------|
| **A 漲停接力** | anchor 前 3 根 K 棒任一日漲幅 ≥ +5% 或 ≥ +9.5% (漲停)，且 anchor 前一日盤中未崩 ≤-4% | 已有突破/強勢動能，今日漲停是接力而非孤立反彈 |
| **B 借券回補** | 借券賣餘 3d 均 / 前 5d 均 ≤ 0.97 或前日單日 ≤ -3% | 空單在止血、空方信心動搖 |
| **C 籌碼集中** | 7 天累積外資 (高盛/摩根/瑞銀/野村/JPM/花旗/美林等) ≥ 2 家 in top10 買超，或 top5 買超合計 ≥ top5 賣超合計 | 主流法人/外資進駐 |
| **D 量能蓄勢** | anchor 前一日量 / 20d 均量 ≥ 1.0 或 / 60d 均量 ≥ 1.5 | anchor 前一日已有資金提前進場 |

### 輸出分群
- **4/4 ⭐⭐⭐⭐ 全訊號**：四項都滿足，最高品質前瞻訊號
- **3/4 ⭐⭐⭐**：三項滿足，明確訊號
- **2/4 ⭐⭐**：兩項滿足，列摘要 (one-line, 用旗標顯示哪些訊號)
- **≤1/4**：純拉抬，僅列代碼（事後無前瞻訊號）

推播文案已標註回測結論 (2026-07)：「≤1/4」分組標題加註「ABD<2 抱20日顯著負超額 — 避開」，對應下方「Layer 2 ABD overlay」回測章節。

### 資料來源
| 指標 | 來源 |
|------|------|
| 漲停清單 | TWSE `MI_INDEX` (上市) + TPEx OpenAPI `tpex_mainboard_daily_close_quotes` (上櫃) |
| 個股 OHLCV | Yahoo Finance (`.TW` / `.TWO`，3 個月) |
| 借券賣出餘額 | FinMind `TaiwanDailyShortSaleBalances` (data_id 可在 register tier 用) |
| 7 天分點 | HiStock `branch.aspx` 爬蟲 (與 `tw_broker_history_lookup` 共享 parser) |

### 使用方式
```bash
# Standalone: 掃當日全市場漲停股
python3 ~/project/tw_stock_tools/tw_limitup_signal.py

# Layer 2 模式: 對指定股票清單評分
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes 4576,3491,3406

# Layer 2 模式: 從 JSON 檔吃 codes (通常 Layer 1 產生)
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes-file /tmp/layer1.json

# 只列 ≥3/4 (更嚴格 Layer 2)
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes-file ... --min-score 3

# 推送到 Telegram (--bot-token / TG_BOT_TOKEN)
TG_BOT_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_limitup_signal.py \
  --codes 4576 --telegram

# 回測指定日期
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --date 2026-04-30

# 自訂報告標題 (供 wrapper 用)
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes ... \
  --header "🎯 Layer 2 — 自訂分析"
```

通常不直接 cron，由 `tw_daily_screen.py` 包裝呼叫。直接 standalone 排程也可：
```cron
0 18 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=... /usr/bin/python3 \
  /home/kun/project/tw_stock_tools/tw_limitup_signal.py --telegram
```

### 性能
- 全市場 (~50 檔漲停) 平行掃描 (6 workers)：約 3-4 分鐘
- HiStock 為主要瓶頸 (1-2 sec/req)，cache 設計按日期，當日重跑會即時返回

### 限制
- HiStock 7 天累積買賣超是時間範圍 (~4/22-4/29)，不是純粹「前一天」籌碼，但能補足 TWSE BSR 只有當日資料的限制
- 4 項訊號是經驗法則 (基於 4576 case study)，未做大規模回測樣本內外驗證
- D (量能) 對近期已大跌補量的股票 (e.g., 4576) 偏嚴，可能漏判 — 屬已知 false negative
- **C 籌碼集中 — 歷史回看無效**：HiStock `branch.aspx` 無日期參數，僅能查「現在」的 7 日視窗。`--date` 回看歷史日時 C 訊號一律回傳 `(無籌碼)` = 0 分（2026-07 起止血；之前的歷史快取若已存入可能含錯誤資料，不信任 `--date` 回看的 C 分）。

### 實例（2026-04-30 全市場掃描，50 檔漲停 / 12 檔 ≥3/4 訊號）
**4/4 全訊號（4 檔）**
- 3707 漢磊 (借券賣餘 -29.2%, 外資 6 家買超 6,639 vs 賣 1,489)
- 3016 嘉晶 (前日量 5.1x 60d, 外資 5 家 GS+UBS+Merrill 包辦)
- 4991 環宇-KY (借券賣餘 -3.7%, 前日量 5.6x 60d)
- 2417 圓剛 (借券賣餘 -19.0%, 前日已連兩漲停)

**3/4（8 檔，含 4576 大銀微系統）**：A+B+C 但量能未爆 / 或 A+C+D 但借券未明顯回補

---

## 11. `concept_momentum/` — 族群熱力 (Theme Heatmap)

策略名：**族群熱力** (盤後 17:00 cron) — 各概念族群動能評分 + 領漲/領跌 + Rerating + 業務轉型偵測

詳細文件見子模組：[`concept_momentum/README.md`](concept_momentum/README.md)

簡要：
- **動能評分**：每概念依 20d 漲幅 / 廣度 / 量比 / RS / 持續天數綜合打分 (0-100)
- **強弱分組**：≥70 強勢 (顯示 🟢 多 leaders + 🔴 空 laggards 配對提示)，<30 弱勢
- **Rerating**：β 調整後與其他概念相關性 ≥ 自己概念 +0.10 → 可能改題材
  - **穩定性過濾** (預設開啟): 須在過去 3 日內連續 ≥2 次指向同一目標概念才推送，避免單日雜訊。穩定後的訊號會顯示「[連續 N 日]」標籤
  - **「兩條沉船」過濾 A/B/C** (預設開啟): 用實際數據驗證後加入的三道強度檢查。
    - **A. 目標族群評分 ≥30** — 排除「目標也是弱勢族群」的偽 rerating（鴻準與 CXO 都在跌、節奏類似 → β-adj corr 高 ≠ 業務轉型）
    - **B. 目標族群為強勢** — score ≥50 或 RS_20d > 0，確認資金真的在流入該目標族群（不是兩個一起被棄）
    - **C. 原屬族群已脫鉤** — own_max_corr < 0，要求股票真的「反向」脫離原概念，不只是相關性下降
  - 推送會在 candidates 後顯示「目標 75 分 RS+18.0%」等強度資訊，並列出排除統計
  - 快取於 `concept_momentum/cache/rerating_history/{date}.json`（A/B/C 在過濾**之前**已存檔，保留歷史訊號密度）
- **業務轉型**：新聞主題與原概念差 ≥1.5x，且 ≥2 個不同關鍵字 (避誤判)
- 推送 Snapshot PNG + Trend PNG + 4 則文字摘要到 Telegram
- **大盤寬度 (Market Breadth)**：dashboard.html 最上方分頁，13 欄 × 60 個交易日。寬度池 = 上市+上櫃 普通股 4 位代號 (~2,300 檔)。包含加權指數 / 漲跌幅 / 股價>20-50-200MA% / 200日新高 / 三大法人 (拆 4 欄) / 融資餘額 + 增減
  - **資料源**：FinMind sponsor tier (`TaiwanStockPrice` 全市場 + `TaiwanStockTotalInstitutionalInvestors` + `TaiwanStockTotalMarginPurchaseShortSale`)
  - **已知 quirk**：FinMind 法人/融資 dataset 在查 `start_date=end_date=X` 時會回傳 X 與 X+1 兩天的資料；fetcher 已加 `if row['date'] != date: continue` 過濾，避免 off-by-one（commit a4b45f1）
  - **歷史 backfill**：首次部署需 200 天 universe 快取，`market_breadth.backfill_universe()` 自動執行 (~3-5 分鐘)；之後每天 cron 1 個 FinMind 呼叫即增量更新
- **快取**：`concept_momentum/cache/market_universe/{date}.json` (全市場日 OHLC) + `concept_momentum/cache/market_breadth/{date}.json` (計算結果)，皆 gitignored
- **🎯 主力雷達歷史榜**：dashboard 第二分頁，10 日視窗。每日 18:00 cron 跑出的主力分點+融資連動結果累積，依「綜合分數 = 連續天數 × (log(Top 分點淨買+1) + sqrt(融資增量)) / 2」排序，Top 30
- **🌅 盤前訊號**：dashboard 第三分頁，10 日視窗。上下兩段顯示轉機接力 (TR ABCD) 與強勢股第二波，含連續入榜天數。強勢股第二波表格自 2026-07-08 起加「層」欄 (⭐/◐/▽ 分層標記，詳「強勢股第二波」節)，排序依 latest_date desc → tier (⭐>◐>▽>未標記) → today_vs_peak asc；自 2026-07-09 起再加「借」欄 (借↓/借↑ 借券急跌變化標記，詳「籌碼確認（借券急跌變化）」節)
- **🌙 借券動向**：dashboard 第四分頁，5 日視窗。上下兩段顯示借券雷達 (議借爆量) 與空頭撤退 (借券賣餘大減)，依時間/變化幅度排序
- **歷史榜快取**：5 個新 dir — `concept_momentum/cache/{broker_radar_history,turnaround_relay_history,second_wave_history,lending_radar_history,short_retreat_history}/{date}.json`，皆 gitignored；歷史由 cron 累積，無 backfill

### 族群熱力回測（`tw_concept_backtest.py`）

驗證族群動能評分是否具有前向預測力；三變體比較：複合加權(A)、純動能 ret_20d(B)、動能+門檻過濾(C，正式推送採用)。

**跑回測（快取命中，無網路呼叫）：**
```bash
FINMIND_TOKEN=$(crontab -l | grep -o 'FINMIND_TOKEN=[^ ]*' | head -1 | cut -d= -f2) \
  python3 tw_concept_backtest.py \
  --json-out concept_momentum/cache/concept_backtest.json
# → 開啟 http://localhost:5000/concept-backtest 看三變體比較表 + 權益曲線
```

**方法摘要：**
- **IC 計算**：允許重疊觀察（每 5d rebalance），加 block bootstrap 95% CI 校正序列自相關。
- **L2 權益曲線**：使用**非重疊**網格（步進 = max(rebalance, H)），確保 total/max_dd/calmar 可信。
  - 舊版重疊灌水問題：H=20d × rebalance=5d → 每筆持倉重複計入 4 次，H=20 total 舊值 ~334% 為 ~4× 灌水。
  - 修正後 H=20 total 下降至 ~72%（strategy）；這是正確值，非退化。
- **流動性過濾 parity**：`ret_20d_score` 改用成交額加權概念指數（同正式版 `analyze_all`）；L2 選股前加 `filter_liquid_stocks`（同正式版 `analyze_concept`）。

**2025-01 起回測結果摘要（新版，非重疊 L2）：**

| 指標 | strategy (A) | benchmark (B) | filter (C) |
|------|-------------|--------------|------------|
| IC @H5 | +0.128 [+0.075,+0.179] | +0.121 | +0.076 |
| IC @H10 | +0.162 [+0.105,+0.229] | +0.138 | +0.099 |
| IC @H20 | +0.194 [+0.127,+0.278] | +0.142 | +0.140 |
| L2 total @H5 | +81.6% | +94.5% | +83.2% |
| L2 total @H10 | +101.5% | +119.7% | +113.5% |
| L2 total @H20 | +72.2% | +52.9% | +110.2% ✓ |
| Calmar @H10 | 5.30 | 12.01 | **12.48** |
| ret/vol @H10 | 0.45 | 0.54 | **0.60** |

**filter vs benchmark 結論：**
- **H5/H10**：filter total 略低於 benchmark（+ 流動性過濾縮小池子），但 H10 ret/vol 與 Calmar 均高於 benchmark，顯示風險調整後 filter 仍具優勢。
- **H20**：filter total (+110.2%) 遠高於 benchmark (+52.9%)，且 H20 L2 CI 下界正 ✓，統計顯著。
- **整體**：廣度/量能**當門檻過濾**（排除項）在 H20 明顯加值；H5 短期差異不顯著。正式推送繼續採用 C 變體。

**舊值 vs 新值對照（重疊灌水說明）：**

| 變體 | H20 total 舊 (重疊) | H20 total 新 (非重疊) | 倍率 |
|------|---------------------|----------------------|------|
| strategy | ~334% | +72.2% | ~4.6× |
| benchmark | ~260% | +52.9% | ~4.9× |
| filter | ~280% | +110.2% | ~2.5× |

舊版 `rebalance=5d × H=20d` 每個持倉日被計入 4 個 bucket，total/max_dd/calmar 全部失真。現已修正為每個持有期各自獨立觀察。

**導航結構 (2026-07-07 重整)**：上方「🔍 單檔快速查詢」列 = 4 個帶股號輸入框的工具 (籌碼價量/合約負債/存貨/前十大股東)；nav 四群組 = 族群動能 (6 分頁) / 訊號監控·依時段 (盤前/借券/主力雷達/成效) / 🧪 策略回測·事件研究 (5 頁) / 即時工具 (盤中模擬/ADR/期貨基差)。每個入口全站僅出現一次。

### 本機看儀表板

```bash
# 手動啟動 Flask（開發用，預設 port 5000）
python3 ~/project/tw_stock_tools/concept_momentum/app.py
# → 開啟 http://localhost:5000/
```

### systemd 自動化（生產用，WSL 開機自啟）

兩個 user systemd unit 已在 `~/.config/systemd/user/`：
- `concept-dashboard.service` — Flask 永久跑在 :5000
- `ngrok-tunnel.service` — ngrok 對外公開 :5000

啟用 lingering 一次（之後重開 WSL/Windows 都會自動跑）：
```bash
sudo loginctl enable-linger $USER
systemctl --user enable concept-dashboard.service ngrok-tunnel.service
systemctl --user start concept-dashboard.service ngrok-tunnel.service
```

查當前 ngrok 公網網址：
```bash
curl -s http://localhost:4040/api/tunnels | python3 -c 'import sys,json;[print(t["public_url"]) for t in json.load(sys.stdin)["tunnels"]]'
```

Free-tier ngrok 每次重啟會發隨機網址；如要固定網址需升級 ngrok Pro 並設 reserved domain。

---

## 10. `tw_daily_screen.py` — 每日兩層篩選工作流（轉機接力策略）

### 用途
每日盤前 07:30 (Mon-Fri) 自動執行兩階段篩選 — 名為「**轉機接力**」策略：

**Layer 1** (`tw_turnaround_screener.py`)
基本面 + 技術面初篩 — 毛利率改善 + 量能放大 + 借券回補 + 季線多頭
全市場 ~3000 檔 → 數檔到數十檔 candidates

**Layer 2** (`tw_limitup_signal.py --codes-file <layer1.json>`)
對 Layer 1 候選做 ABCD 接力型訊號評分 — 找出「明日續攻機率最高」子集

兩層結果都推送 Telegram，使用者隔日可用實際漲跌「後照鏡」驗證 Layer 2 嚴格度，
逐步調整 ABCD 訊號條件。

### 流程
```
07:30 cron (盤前 1.5 hr)
  ↓
Layer 1 — 轉機 (~1 min warm cache, ~5-10 min cold cache)
  ├ tw_turnaround_screener --json-out /tmp/layer1.json --telegram
  │   毛利率↑ + 量能↑ + 借券↓ + 季線多頭排列 + 排除 GM<0%
  │   → 推送 Layer 1 表格摘要到 TG
  ↓
Layer 2 — 接力 (~1-2 min, 視 Layer 1 候選數)
  ├ tw_limitup_signal --codes-file /tmp/layer1.json --min-score 2 --telegram
  │   ABCD 接力訊號評分 (漲停接力/借券回補/籌碼集中/量能蓄勢)
  │   → 推送 ABCD 分級結果到 TG (4/4/3/4/2/4)
  ↓
完成 (盤前可看完，9:00 開盤前布局)
```

「**轉機接力**」(Turnaround Relay) — Layer 1 找已轉機的標的池，Layer 2 從中
挑出技術面準備接力突破的子集。資料用前一交易日收盤，盤前推給使用者參考布局。

### 使用方式
```bash
# 預設模式：兩層都跑、推送 TG
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_daily_screen.py

# 不推 TG (測試)
python3 ~/project/tw_stock_tools/tw_daily_screen.py --no-tg

# Layer 2 更嚴格 (只看 ≥3/4)
python3 ~/project/tw_stock_tools/tw_daily_screen.py --layer2-min 3

# 用 concepts universe (~190 檔，更快)
python3 ~/project/tw_stock_tools/tw_daily_screen.py --universe concepts
```

### 排程（crontab）
```cron
# 每天盤前 07:30 (Mon-Fri) 兩層篩選 — 轉機接力策略
30 7 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=... /usr/bin/python3 \
  /home/kun/project/tw_stock_tools/tw_daily_screen.py \
  >> /home/kun/project/tw_stock_tools/daily_screen.log 2>&1
```

### 為什麼分兩層？
- **Layer 1 嚴格但靜態**：基本面 + 量能 + 借券 — 「值得關注」的池子，可能 4-30 檔
- **Layer 2 動態 + 接力型**：在 Layer 1 池子內找「明日突破機率高」— 更積極
- **後照鏡學習**：用實際漲跌結果驗證 Layer 2 訊號是否能 predict，逐步調 ABCD threshold

### 實例（2026-04-30，--universe concepts）
Layer 1 → 4 檔候選：3491 昇達科, 4576 大銀微系統, 3406 玉晶光, 6166 凌華

Layer 2 → 4576 大銀微系統 3/4 ⭐⭐⭐ (今天剛好漲停 ✅ 印證)
- A 近 3 日內漲停 +9.9%
- B 前日借券賣餘 -3.7%
- C 外資 3 家齊買 (高盛/MS/JPM)
- D 量能未過門檻 (大銀微平日成交量低)

3491 昇達科 / 3406 玉晶光 各 2/4，未達 ≥3/4 接力門檻。

---


---

## 轉機接力回測(tw_turnaround_backtest)
## 轉機接力回測 (`tw_turnaround_backtest.py`)

Layer 1 四濾網（ABCD）的首次系統性回測，採 point-in-time 事件研究法。

### 方法

**資料與 PIT 規則**

- 毛利率：FinMind `TaiwanStockFinancialStatements`；`date` 欄是季末日，非公告日
- 財報**可用日**（law-deadline rule，保守）：

  | 季末   | 可用日  |
  |--------|---------|
  | 3/31   | 5/15    |
  | 6/30   | 8/14    |
  | 9/30   | 11/14   |
  | 12/31  | 翌年 3/31|

  多數公司提早公告，故此規則**低估** edge（不高估）。
- 量能/季線：v2 price panel 未還原 close/volume，與正式篩選器同口徑
- 借券餘額：as-of 截斷到事件日 t

**訊號重建**
import 正式 `tw_turnaround_screener` 純函數逐日跑；episode 去重採 cooldown=max_horizon，同一波只取首次進場。

**Layer 2 ABD overlay**
在每個 Layer 1 事件日計算 A（漲停接力）/ B（借券回補）/ D（量能蓄勢）三個 overlay 訊號（C 訊號需分點歷史無公開記錄，誠實跳過），依總分 ≥2 vs <2 分兩組，比較前向超額報酬差異。

**進場假設**：訊號日隔日還原開盤（07:30 盤前推播後最早可成交時間）。

**IS/OOS 切窗**：`--is-end 20260331` 把回測切成 IS（`--start` ~ `--is-end`）/ OOS（`--is-end` 翌日 ~ 期末）兩窗，各自輸出 `summarize_events` 摘要於 `result.windows.{IS,OOS}[h]`；不給則行為與 schema 完全不變（供參數敏感度掃描腳本用）。

### Headline 數字（2025-01-01 起）

> 首跑結果（`tw_turnaround_backtest.py --start 2025-01-01`，2026-07-06 完成）：

- **Episodes**：613（universe 1895 檔，GM 可過關 1482 檔）
- **H=5d**：超額 +0.17% CI [-0.53, 0.87] t=0.48 淨 -0.30%；ABD≥2: +0.29% vs ABD<2: +0.06%
- **H=10d**：超額 +0.15% CI [-0.94, 1.28] t=0.27 淨 -0.32%；ABD≥2: +0.59% vs ABD<2: -0.28%
- **H=20d**：超額 -1.14% CI [-2.65, 0.39] t=-1.46 淨 -1.61%；ABD≥2: +0.12% vs ABD<2: -2.39% ★

**★ 關鍵發現**：ABD overlay 分組差異在 H=20d 最為顯著：
- ABD<2 超額 -2.39% CI [-4.24, -0.42]，t=-2.42，CI 全負 → 統計顯著的負 edge
- ABD≥2 超額 +0.12%（CI 含 0，非顯著），但明顯優於 ABD<2 組（差值 +2.51pp）
- 解讀：Layer 1 單獨信號不足，**ABD<2（低 overlay 分數）應視為迴避警號**

### Live-History Overlap 驗證

取 `concept_momentum/cache/turnaround_relay_history/2026*.json` 的 layer1_passed 記錄（37 個交易日，1192 組 (date, code) 對），
與回測同日事件集合比對：overlap = **5.1%（61/1192）**。

差距來源（低 overlap 的結構性解釋）：
1. **Cooldown 去重（最主要）**：回測對每檔股票施加 cooldown=20 天，實際運行不去重；若一檔連過 10 天，回測只計 1 次，live 計 10 次 → overlap 分母膨脹 10×
2. **法定死線 vs 實際公告**：回測用保守法定死線，多數公司早於死線公告，live 可先看到最新 FS
3. **面板口徑微差**：v2 面板快取 vs 盤前即時快取時間戳差異

> 本 overlap 偏低（＜30%）主要為設計上的保守性（cooldown + PIT），非訊號失準。

### 限制

去重前逐點保真度驗證：對 live 歷史 1,169 個 (股,日) 以回測 PIT 邏輯重算四濾網，88.7% 全數通過（A 90.1% / B 99.1% / D 99.7% / C 99.7%）；殘差主因為 PIT 法定死線保守性（設計如此）與 live 端 GM 快取過期（已由財報季 TTL 修正改善）。5.1% episode overlap 為 cooldown 稀釋後的預期值。

1. **C 訊號缺失**：Layer 2 只含 A/B/D，若 C（籌碼集中）有效，ge2 組 edge 可能被低估
2. **樣本期間偏短**：面板 start=2025-01-01，約 1.5 年，多頭友善期；空頭盤 edge 未知
3. **PIT 保守**：財報用法定死線，比多數公司實際公告晚，回測 edge 低估
4. **滑價假設**：成本 0.471% 假設零滑價，轉機股流動性偏低時實際成本更高

Dashboard 頁面：`/turnaround-backtest`（仿第二波頁，多 Layer2 ge2/lt2 對照表）

---

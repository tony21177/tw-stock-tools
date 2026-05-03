# 台股借券 / 融資 / 籌碼 / 概念動能分析工具組

十二大功能：

1. 借券議借異常監控（每日排程推送）→ `tw_lending_monitor.py`
2. 借券賣出餘額大幅減少監控（每日排程推送）→ `tw_lending_monitor.py`
3. 單檔借券狀況查詢（CLI）→ `tw_lending_lookup.py`
4. 融資維持率預警全市場掃描（含批次分布）→ `tw_margin_monitor.py`
5. 單檔融資維持率估算 + 批次 cohort 分析（CLI）→ `tw_margin_lookup.py`
6. **分點+融資連動分析（每日排程推送）** → `tw_broker_monitor.py` / `tw_broker_lookup.py`
7. **概念動能監控 + Rerating 偵測（每日排程推送 PNG + 網頁儀表板）** → `concept_momentum/`
8. **台股 ↔ 美股 peer 相關性查詢（CLI）** → `tw_us_correlation.py`
9. **Turnaround 篩選器（毛利率改善 + 量能放大 + 借券回補）** → `tw_turnaround_screener.py`
10. **ABCD 接力型訊號分析（CLI / 也可吃 Layer 1 candidates 做 Layer 2 過濾）** → `tw_limitup_signal.py`
11. **每日兩層篩選工作流（19:00 cron）** → `tw_daily_screen.py`
12. **沉睡巨人篩選器（曾 10 倍 / 跌 ≥50% / 沉睡 ≥5y / 量縮整理）** → `tw_dormant_giants.py`

所有工具放在 `~/project/tw_stock_tools/`，cron 設定每天排程推送到 Telegram 群組。
概念動能子模組詳見 `concept_momentum/README.md`。

---

## 1. `tw_lending_monitor.py` — 借券異常監控

### 用途
每日自動掃描全市場，找出兩類異常：
- **議借量突增**：議借量 > 5 日均量 × 2，且利率 <1% 或 >7%
- **借券賣出大幅減少**：借券賣出餘額比前日減少 >10%

### 資料來源
- TWSE SBL API（`t13sa710`）：議借交易明細，上市+上櫃皆包含
- TWSE TWT93U：每日借券賣出餘額
- Yahoo Finance：股價、成交量、漲跌幅

### 核心邏輯

**議借量突增檢測**
1. 抓過去 6 個交易日的議借交易（含當日）
2. 依股票代號彙總每日議借量，利率用「成交量加權平均」
3. 計算過去 5 日平均量
4. 篩選：當日量 > 5 日均 × 2 且 利率 <1% 或 >7%
5. 為命中標的查當日股價、成交量變化

**借券賣出減少檢測**
1. 抓當日 TWT93U 餘額表
2. 針對每檔股票：當日餘額 vs 前日餘額
3. 篩選：減少 >10%（即 `(today - prev) / prev < -10%`）
4. 額外標記「借券減少且今日上漲」= 空方回補 + 股價漲 = 可能轉多訊號
5. 數值從股轉張：÷ 1000

### 使用方式
```bash
# 手動跑（列在終端機）
python3 ~/project/tw_stock_tools/tw_lending_monitor.py
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --date 20260421

# 分別執行不同 mode
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode lending   # 只跑議借
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode sbl       # 只跑借券賣出減少
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode both      # 兩個都跑（預設）

# 推送到 Telegram
TG_BOT_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode lending --telegram
```

### 排程（crontab）
```
0 16 * * 1-5 TG_BOT_TOKEN=... /usr/bin/python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode lending --telegram >> ~/project/tw_stock_tools/lending_monitor.log 2>&1
30 21 * * 1-5 TG_BOT_TOKEN=... /usr/bin/python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode sbl --telegram >> ~/project/tw_stock_tools/lending_monitor.log 2>&1
```

- 議借：週一到五下午 4:00
- 借券賣出：週一到五晚上 9:30（借券賣出餘額要 21:00 後才公布）

### 輸出格式
分兩則訊息推送：
1. 議借異常：分「利率 <1%」和「利率 >7%」兩區塊
2. 借券賣出減少：分「借券減少且今日上漲（轉多訊號）」和「其他借券減少標的」兩區塊

---

## 2. `tw_lending_lookup.py` — 單檔借券狀況查詢

### 用途
輸入股票代號，印出「今日 / 昨日」的：
- 借券交易逐筆明細（定價 / 競價 / 議借）
- 還券明細逐筆（含原借入日期、借券天數）
- 借券賣出餘額（前日 / 賣出 / 還券 / 調整 / 當日 / 變化）

### 資料來源
- TWSE SBL `t13sa710`：借券交易
- TWSE SBL `t13sa870`：還券明細（含借入日期、借券天數）
- TWSE TWT93U：上市借券賣出餘額
- TPEx `/www/zh-tw/margin/sbl`：上櫃借券賣出餘額
- Yahoo Finance：即時股價（依市場自動用 `.TW` 或 `.TWO`）

### 核心邏輯
1. 依 Yahoo Finance 判斷上市 / 上櫃 → 決定用 TWSE 還是 TPEx 的 SBL API
2. 抓近 2 個交易日的借券交易，依日期分組，每筆列出
3. 抓 2025-01 至今的還券明細（因為借入日可能幾個月前），篩選「完成還券日 = 今日 / 昨日」的逐筆列出
4. 借券賣出餘額數值從股 ÷ 1000 轉張

### 使用方式
```bash
python3 ~/project/tw_stock_tools/tw_lending_lookup.py 2330
python3 ~/project/tw_stock_tools/tw_lending_lookup.py 3491 --date 20260421
```

### 輸出範例
```
2313 COMPEQ MANUFACTURING [上市]
現價: $222.50  -9.92%

━━━ 今日 (2026-04-22) ━━━
借券交易:
  合計: 129張 (3筆)
  [競價] 14張 @ 1.00%
  [議借] 80張 @ 1.75%
  [議借] 35張 @ 1.75%
還券明細: 無還券
借券賣出餘額: 無資料（21:00 後公布）

━━━ 昨日 (2026-04-21) ━━━
借券交易:
  合計: 542張 (2筆)
  [議借] 454張 @ 1.65%
  [議借] 88張 @ 1.65%
還券明細:
  合計: 716張 (3筆)
  [議借] 304張 @ 1.75% | 借於 04/14 | 7天
  [議借] 262張 @ 1.75% | 借於 04/13 | 8天
  [議借] 150張 @ 1.75% | 借於 04/10 | 11天
借券賣出餘額:
  前日餘額: 26,226張
  當日賣出: 1,286張
  當日還券: 350張
  當日餘額: 27,162張
  餘額變化: +3.6%
```

### 注意
- 還券明細（t13sa870）= TWSE SBL 平台的還券筆數
- 借券賣出餘額的「當日還券」= 所有管道（含券商/證金庫存）的還券總量
- 兩者通常不同，一個看逐筆、一個看總量

---

## 3. `tw_margin_monitor.py` — 融資維持率預警（全市場掃描）

### 用途
估算全市場每檔股票的融資維持率，篩出警戒標的（預設 <140%）。

### 估算公式
```
融資維持率 = 現價 / (加權平均買進價 × 融資成數) × 100%

融資成數：
  上市一般股：60%
  上櫃一般股：50%
  （警示股 / 管理股 / 全額交割股另計，目前未特別處理）

警戒線 140%，追繳線 130%
追繳觸發價 = 加權成本 × 融資成數 × 1.30
```

### 加權成本：FIFO 演算法
對每檔股票，從過去 3 個月每日的融資資料重建「成本」：

```
For each trading day d (oldest → newest):
  today_price = 當日收盤價
  
  If 融資買進 > 0:
    add a lot: (融資買進, today_price) to queue tail
  
  reduce_amount = 融資賣出 + 融資現金償還
  While reduce_amount > 0 and queue not empty:
    oldest_lot = queue head
    If oldest_lot.volume <= reduce_amount:
      reduce_amount -= oldest_lot.volume
      pop from queue
    Else:
      oldest_lot.volume -= reduce_amount
      reduce_amount = 0

加權成本 = Σ(lot.volume × lot.price) / Σ(lot.volume)
剩餘張數 = Σ(lot.volume)  （應等於當日融資餘額）
```

**這是市場整體的估算**，不是單一投資人的真實成本。前提假設：先進先出，舊部位優先結清。

### 資料來源
- 今日快照：`openapi.twse.com.tw` + `tpex.org.tw/openapi/`（避開 www 網站的反爬限制）
- 3 個月歷史：FinMind `TaiwanStockMarginPurchaseShortSale`（per-stock，每檔股票一次 API）
- 股價：Yahoo Finance 3 個月日線

### 使用方式
```bash
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_monitor.py
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_monitor.py --threshold 150 --min-balance 1000
```

### 主要參數
- `--threshold 140`：維持率警戒線（百分比），篩出 < 此值的標的
- `--min-balance 500`：融資餘額門檻（張），低於不分析
- `--max-stocks 0`：最多分析前 N 檔（0 = 全部）
- `--telegram`：推送到 Telegram
- `--date YYYYMMDD`：指定日期（預設今天）

### 快取機制
為避免 FinMind 免費版 600 req/hr 限制，資料會快取到：
```
~/project/tw_stock_tools/margin_cache/finmind_{code}_{YYYY-MM-DD}.json
```
第一次跑要抓 500+ 檔大約 10-15 分鐘（會斷斷續續因為 rate limit），
之後同一天跑會走快取，只要 1-2 分鐘。

### 已知限制
1. 融資成數用預設值，實際某些股票降低成數（40%、30%）未特別處理
2. FIFO 是市場整體加權，不等於個別投資人真實成本
3. FinMind 免費版 600/hr 限制，全市場單日首次跑可能跑不完（~600 檔後會被擋）
4. Yahoo Finance 偶爾 rate limit，失敗的股票會自動跳過

---

## 4. `tw_margin_lookup.py` — 單檔融資維持率查詢 + Cohort 分析

### 用途
輸入股票代號，輸出：
- 整體 FIFO 加權成本 + 維持率 + 警戒/追繳價
- **批次（cohort）分布**：把融資餘額按進場日拆成多批，看不同進場價的維持率
- 主要批次明細（佔總餘額 ≥5% 的大量進場日）

### 為什麼要做 cohort 分析？
單一加權平均會掩蓋風險。例如 2313 整體維持率 151%（看似安全），但拆開後追蹤量 92% 都已在警戒區（130-140%），只是被舊部位拉高平均。Cohort 才是真實的風險分布。

### 三種扣減規則（`--method`）
餘額減少時，要把減少量歸因到哪一批 cohort？三種假設：

| Method | 假設 | 適用情境 |
|--------|------|----------|
| `fifo`（預設） | 老批先扣（先進先出） | 最常見假設：老倉達到停利停損先出場 |
| `lifo` | 新批先扣 | 假設新進場恐慌賣壓較強 |
| `proportional` | 全部按比例扣 | 中性視角，無方向性 |

同一檔股票用不同 method 結果差異巨大。建議搭配使用做壓力測試。

### Cohort 演算法（balance-change 法）
```
For each trading day d (oldest → newest):
  delta = today_balance - prev_balance

  If delta > 0:
    add cohort {date: d, volume: delta, price: today_close}

  If delta < 0:
    reduce = -delta
    Match against cohorts using selected method:
      fifo: reduce from oldest
      lifo: reduce from newest
      proportional: scale all by (1 - reduce/total)
    若仍有剩餘，從 legacy（觀察期前的舊部位）扣

當前活躍 cohorts → 各自算維持率 → 分桶（<130, 130-140, 140-150, 150-170, 170+）
```

**Legacy 概念**：3 個月觀察期之前就存在的部位，因為沒有當時的成本資料，無從估算維持率。獨立顯示「舊部位 X 張」。

### 使用方式
```bash
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_lookup.py 2313
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_lookup.py 3035 --date 20260422
```

### 輸出範例
```
3035 FARADAY TECHNOLOGY [上市]
現價: $168.50  -5.87%

【融資維持率估算】
加權成本: $179.00 (FIFO 過去 3 個月)
融資餘額: 15,780 張
融資成數: 60%
估算維持率: 156.9%  🟢 尚可（150-170%）

【關鍵價位】
140% 警戒價: $150.36  (再跌 10.77%)
130% 追繳價: $139.62  (再跌 17.14%)

【近期融資買進（最近 5 筆）】
  04/16: 買 366 張 @ $156.50
  04/17: 買 423 張 @ $159.00
  04/20: 買 1,683 張 @ $174.50
  04/21: 買 1,734 張 @ $180.00
  04/22: 買 1,317 張 @ $179.00
```

### 狀態分級
- 🔴 危險（<140%）
- 🟡 警戒（140-150%）
- 🟢 尚可（150-170%）
- ✅ 安全（>170%）

---

## 5. `tw_broker_monitor.py` / `tw_broker_lookup.py` — 分點+融資連動分析

### 用途
找出疑似「用融資做短線」的券商分點：在過去 N 天連續買超某檔，且這幾天該股的融資餘額也同步增加，且分點當日淨買 vs 當日融資淨增量呈正相關。

### 核心邏輯

對每一檔目標股票：
1. 抓近 N 天（預設 5）BSR 分點資料 + FinMind 融資歷史
2. 對每個分點計算：
   - **連續買超**：N 天內 ≥3 天買超 + 每天買超 >當日 5% 總量
   - **融資同步**：N 天累積融資餘額淨增加 > 0
   - **相關係數**：分點當日淨買 vs 當日融資淨增量的 Pearson 相關 ≥ 0.5
3. 三項都符合 → 列入「疑似用融資做短線」名單

### 資料源

| 資料 | 來源 | CAPTCHA 處理 |
|------|------|--------------|
| 上市分點買賣量 | TWSE BSR `bsr.twse.com.tw/bshtm/` | 圖片 CAPTCHA → ddddocr |
| 上櫃分點買賣量 | TPEx `brokerBS.html` | Cloudflare Turnstile → patchright + Xvfb |
| 融資餘額歷史 | FinMind `TaiwanStockMarginPurchaseShortSale` | - |

**重要限制**：BSR 與 TPEx 兩邊都只有「當日」資料，沒有歷史。所以必須每天 cron 抓取累積，第 5 天起分析才有完整視窗。

### CAPTCHA 突破方法

**TWSE BSR（簡單圖片）**：
- 套件：`pip install ddddocr`
- 解碼成功率約 95%，失敗自動重試
- 搭配 Session 維持 ASP.NET ViewState

**TPEx（Cloudflare Turnstile）**：
- 套件：`pip install patchright`（playwright fork，反偵測）
- 系統：`apt install xvfb`（虛擬顯示器）
- 必須用 `headless=False` + Xvfb 才能讓 Turnstile 自動解鎖（純 headless 會被 Cloudflare 偵測拒絕）
- 用 `browser.new_page()` 預設 context，**不要**自訂 viewport/locale/UA

### 使用方式
```bash
# 單檔查詢（需要至少 2 天 BSR 歷史 cache）
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_broker_lookup.py 2313

# 全市場掃描 + 推送 Telegram
TG_BOT_TOKEN=xxx FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_broker_monitor.py --top-n 100 --telegram
```

### 掃描標的選擇

預設每天掃兩組標的的聯集：
1. **Top N 大融資餘額**（預設 100）：用 TWSE/TPEx OpenAPI 取得當日融資餘額排序前 N 檔
2. **概念動能強勢族群成分股**（評分 ≥ 70）：讀 `concept_momentum/cache/results/analysis_{today}.json`，把當天評分達門檻的所有族群成分股加入掃描範圍

效果：避免某檔不在融資 Top 100 但在強勢概念中的個股漏抓 BSR 快取。可用 `--no-concept-strong` 關閉、`--concept-min-score 80` 調整門檻。

### 排程
```
0 18 * * 1-5 ... tw_broker_monitor.py --top-n 100 --telegram
```
週一到五傍晚 6:00（BSR 約 17:30 公布）累積資料並執行分析。第 5 個交易日起分析開始有效。
注意：concept_momentum cron 設在 17:00 跑，會把 `analysis_{today}.json` 存好讓 18:00 broker_monitor 讀取。

### 已知限制
1. BSR 沒有歷史，需從今日起累積
2. Cloudflare Turnstile 偶爾偵測（10-20% 失敗率，會自動重試）
3. 無法區分「分點買進」中現股 vs 融資的比例 — 只能用相關性做 inference
4. 真實分點融資資料需要付費（FinMind 贊助版的 `TaiwanStockTradingDailyReport`，未實作）

---

## 6. `tw_broker_history_lookup.py` — 個股分點歷史查詢（HiStock 爬蟲）

### 用途
TWSE BSR 只開放當日資料，本工具用 HiStock 補足歷史視角，輸出指定股票過去 N 天累積買/賣超的 Top 30 分點。

### 資料來源
HiStock `histock.tw/stock/branch.aspx?no=<code>&day=<N>`
支援 N：7, 10, 14, 30, 60, 90, 180, 270, 365

### 使用方式
```bash
python3 ~/project/tw_stock_tools/tw_broker_history_lookup.py 3035            # 預設 10 天
python3 ~/project/tw_stock_tools/tw_broker_history_lookup.py 2330 --days 30 --top 20
```

### 輸出
- 期間（from-to 日期）
- 買超 Top N 分點：分點名稱 + 買張 + 賣張 + 淨買 + 60 天均價
- 賣超 Top N 分點：同上

### 限制
- HiStock 限制每張表 Top 30 分點，無法取得全部分點
- 累積買賣超，無單日分布
- 屬非官方頁面，HiStock 改版會壞

---

## 7. `tw_us_correlation.py` — 台股 ↔ 美股 peer 相關性查詢

### 用途
找出台股哪些標的真的跟著指定美股 peer 動。可指定一個概念內掃描，或直接對全市場（34 個概念去重共 ~190 檔）跑相關性。

典型用途：
- 「想做 NVDA / BE / AMD 行情但只能買台股 → 找最高相關度的影子股」
- 「驗證某概念是不是真的跟著 narrative 美股動」（e.g., 台股 ASIC 跟 AVGO 連不連動？）
- 「同一家公司 ADR vs 母股，相關性能多高？」（TSM vs 2330 = +0.47，揭示日線級別 ADR 連動上限）

### 資料來源
Yahoo Finance（query1.finance.yahoo.com）— 同 `concept_momentum/data_fetcher.py`，台股自動加 `.TW` / `.TWO` 後綴，美股直接用 ticker。資料範圍依 window 自動切換：window ≤ 100 用 `6mo`，101–200 用 `1y`，> 200 用 `2y`。

### 計算邏輯（β 調整版，預設）
1. 抓近 6 個月或 1 年日線
2. 算每日 daily return: `(close_t - close_{t-1}) / close_{t-1}`
3. **β 調整**：
   - 台股 vs `^TWII`（台灣加權）算 β（線性迴歸斜率：`Cov(s,m)/Var(m)`）
   - 美股 vs `^GSPC`（S&P 500）算 β
   - excess_return = stock_return - β × market_return
   - 目的：去除「全球 risk-on 共漲」的雜訊，留下真正的個股 idiosyncratic 連動
4. **時差對齊**：TPE D ↔ US D-1（TPE D 反應的是前一晚 US 收盤，US D 的 session 在 TPE D 之後才發生）
5. Pearson 相關係數於指定視窗（預設 240 個 TPE 交易日，約 1 年；可用 `--window 60` 看近期 narrative）

### 兩種模式
| 模式 | 用途 | 數值範圍 | 風險 |
|------|------|---------|------|
| **β 調整（預設）** | 找真正 idiosyncratic 連動 | 通常較低（0.2–0.5） | 數字小看似不顯著 |
| `--raw` | 直觀「美股漲台股也漲」 | 通常較高（0.4–0.7） | 含全球 β，可能誤判共漲為連動 |

實例：1605 華新 vs AMD
- raw：+0.35（看起來中等相關）
- β 調整：+0.19（揭示其實沒實質連動，只是兩邊各自吃了 AI risk-on）

### 使用方式
```bash
# 單一概念查詢（預設用該概念內建美股 peer）
python3 ~/project/tw_stock_tools/tw_us_correlation.py ASIC自研晶片

# 指定特定 peer
python3 ~/project/tw_stock_tools/tw_us_correlation.py ASIC自研晶片 --peer MRVL

# 全市場掃描（推薦）— 不漏掉跨概念的高相關股；預設 240 天視窗
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer NVDA

# 看近期 narrative（60 天視窗）
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer BE --window 60

# 跑 raw 看共動，含全球 β（小心雜訊）
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer BE --raw

# 列出所有概念與預設 peer mapping
python3 ~/project/tw_stock_tools/tw_us_correlation.py --list
```

### 預設美股 peer mapping
腳本內 `US_PEERS` dict 涵蓋全部 34 個概念，例如：
- ASIC自研晶片 → AVGO, MRVL, ALAB
- AI伺服器_ODM → DELL, HPE, SMCI
- AI伺服器_電源 → VRT, ETN, GEV
- NVIDIA供應鏈 → NVDA
- HBM記憶體 → MU
- CPO_矽光子 → ANET, CIEN, COHR
- 半導體設備 → AMAT, LRCX, KLAC, ASML
- SiC功率元件 → ON, WOLF
- 重電_電網 → ETN, GEV, HUBB

每季可依市場焦點微調此 dict。

### 解讀門檻
| 範圍 | 圖示 | 意義 |
|------|------|------|
| ≥ 0.6 | 🟢 強相關 | 直接 narrative driver，幾乎可當 proxy 交易 |
| 0.3–0.6 | 🟡 中等 | 有 narrative 連動，可作為 hedge 候選 |
| < 0.3 | ⚪ 弱 | 自己走自己的，台美連動弱 |

注意：β 調整版數字普遍較低 — `β-adj 0.3 ≈ raw 0.5` 的訊號強度。

### 已知限制
- 日線資料的時差對齊已盡量處理（TPE D ↔ US D-1），但仍有 ADR 溢價、隔夜 gap、匯率影響
- `--raw` 模式的高相關常常是「共同蹭 macro narrative」，要用 β 調整版驗證
- ADR 同公司（TSM vs 2330）的相關性上限約 +0.47（時段錯開、資訊分裂）— 不要期待 1.0
- 視窗選擇影響大：60 天反映近期 narrative，180/240 天反映中長期；兩者差距大代表近期有 regime change（如台船 60 天 +0.46 vs 240 天 +0.14，60 天為短期巧合）
- 預設 240 天是為了過濾掉短期雜訊，得到較穩定的相關性畫面；要看近期變化用 `--window 60`

---

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

### 四項訊號（各 1 分，滿分 4）
| 訊號 | 條件 | 含義 |
|------|------|------|
| **A 漲停接力** | 過去 3 日內 (不含今日) 任一日漲幅 ≥ +5% 或 ≥ +9.5% (漲停)，且前日盤中未崩 ≤-4% | 已有突破/強勢動能，今日漲停是接力而非孤立反彈 |
| **B 借券回補** | 借券賣餘 3d 均 / 前 5d 均 ≤ 0.97 或前日單日 ≤ -3% | 空單在止血、空方信心動搖 |
| **C 籌碼集中** | 7 天累積外資 (高盛/摩根/瑞銀/野村/JPM/花旗/美林等) ≥ 2 家 in top10 買超，或 top5 買超合計 ≥ top5 賣超合計 | 主流法人/外資進駐 |
| **D 量能蓄勢** | 前日量 / 20d 均量 ≥ 1.0 或 / 60d 均量 ≥ 1.5 | 前日已有資金提前進場 |

### 輸出分群
- **4/4 ⭐⭐⭐⭐ 全訊號**：四項都滿足，最高品質前瞻訊號
- **3/4 ⭐⭐⭐**：三項滿足，明確訊號
- **2/4 ⭐⭐**：兩項滿足，列摘要 (one-line, 用旗標顯示哪些訊號)
- **≤1/4**：純拉抬，僅列代碼（事後無前瞻訊號）

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

### 實例（2026-04-30 全市場掃描，50 檔漲停 / 12 檔 ≥3/4 訊號）
**4/4 全訊號（4 檔）**
- 3707 漢磊 (借券賣餘 -29.2%, 外資 6 家買超 6,639 vs 賣 1,489)
- 3016 嘉晶 (前日量 5.1x 60d, 外資 5 家 GS+UBS+Merrill 包辦)
- 4991 環宇-KY (借券賣餘 -3.7%, 前日量 5.6x 60d)
- 2417 圓剛 (借券賣餘 -19.0%, 前日已連兩漲停)

**3/4（8 檔，含 4576 大銀微系統）**：A+B+C 但量能未爆 / 或 A+C+D 但借券未明顯回補

---

## 10. `tw_daily_screen.py` — 每日兩層篩選工作流

### 用途
每日 19:00 (Mon-Fri) 自動執行兩階段篩選：

**Layer 1** (`tw_turnaround_screener.py`)
基本面 + 技術面初篩 — 毛利率改善 + 量能放大 + 借券回補 + 季線多頭
全市場 ~3000 檔 → 數檔到數十檔 candidates

**Layer 2** (`tw_limitup_signal.py --codes-file <layer1.json>`)
對 Layer 1 候選做 ABCD 接力型訊號評分 — 找出「明日續攻機率最高」子集

兩層結果都推送 Telegram，使用者隔日可用實際漲跌「後照鏡」驗證 Layer 2 嚴格度，
逐步調整 ABCD 訊號條件。

### 流程
```
19:00 cron
  ↓
Layer 1 (~30 min cached)
  ├ tw_turnaround_screener --json-out /tmp/layer1.json --telegram
  │   → 推送 Layer 1 表格摘要到 TG
  ↓
Layer 2 (~1-2 min for typical 4-10 candidates)
  ├ tw_limitup_signal --codes-file /tmp/layer1.json --min-score 2 --telegram
  │   → 推送 ABCD 評分結果到 TG (4/4/3/4/2/4 分級)
  ↓
完成
```

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
# 每天 19:00 (Mon-Fri) 兩層篩選
0 19 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=... /usr/bin/python3 \
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

## 12. `tw_dormant_giants.py` — 沉睡巨人篩選器

### 用途
找出「曾經 10 倍股、跌幅 ≥50%、沉睡 ≥5 年、近期長時間量縮震狹幅整理」的標的。
這類股票的特徵：
- 過去有故事、有資金推升過 → 證明商品/題材有想像空間
- 但現在已被市場徹底遺忘，籌碼洗淨、套牢盤消化
- 波動率被壓到底、量也縮到底 → 沒人關心
- 若有新催化事件 (產業景氣回暖、新題材、業務轉型)，向上爆發力大且阻力小

### 五項過濾 (各須滿足)
| 條件 | 預設 | 意義 |
|------|------|------|
| **A 曾 10 倍股** | peak/peak前低點 ≥ 10x | 還原收盤峰值除以峰前低點，且峰前需有 ≥3 年資料才算數 (避開 Yahoo 起點即峰值的假訊號) |
| **B 跌 ≥ 50%** | current ≤ 50% × peak | 從峰值大幅修正 |
| **C 峰值 ≥ 5 年前** | peak_date ≤ today − 5y | 退潮已久 |
| **D 近 5 年無炒作** | 5y max/min < 3x，任 120td 滑窗 max/min < 1.5x | 確認沒被再炒過 |
| **E 量縮震盪** | 60d 振幅 < 10%，60d 量 ≤ 75% × 3y 平均量 | 真正的窄幅整理 |

### 資料源
| 資料 | 來源 |
|------|------|
| 還原股價 | Yahoo Finance `adjclose` (含 split + dividend；多數 case 也涵蓋減資)。FinMind `TaiwanStockPriceAdj` 需付費，本工具用 Yahoo 替代 |
| Universe | FinMind `TaiwanStockInfo` (與 turnaround_screener 共享 universe_all 快取，4 位數普通股) |

注意：Yahoo TW 資料起點 ~2007，2007 前已達峰的個股 (e.g. 6244 茂迪 2006 高點 >900) 可能漏抓。
透過 `--min-pre-peak-years` (預設 3) 強制要求峰前 3 年資料，自動排除這類「資料截斷」假訊號。

### 使用方式
```bash
# 預設掃全市場
python3 ~/project/tw_stock_tools/tw_dormant_giants.py

# 推送 Telegram
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_dormant_giants.py --telegram

# 放寬倍數 (預設 10x 太嚴可改 5x)
python3 ~/project/tw_stock_tools/tw_dormant_giants.py --min-peak 5

# 放寬量縮條件
python3 ~/project/tw_stock_tools/tw_dormant_giants.py \
  --max-60d-range 0.15 --vol-decline-ratio 1.0
```

### 性能
全市場 ~3000 檔，cold cache (Yahoo 抓 18 年) ~5-10 分鐘 (6 workers 平行)；
warm cache 後續查詢 < 1 分鐘 (cache 7 天)。

### 排序邏輯
按 `沉睡年數 × (0.20 − 60d 振幅) × (0.40 − 量比) × 倍數/10` 由大到小排序，
即「越久沉睡 + 越窄整理 + 越大歷史倍數」越優先。

### 實例（2026-05-03 全市場掃描）
篩選漏斗：2,141 → A:905 → AB:281 → ABC:105 → ABCD:4 → **ABCDE:2 檔**

**2496 卓越** [上市] — 經典案例
- 曾 10 倍：2011-10 10.9 → 2017-05 161.7 = **14.9x**
- 跌幅：今價 64.6 = 峰值 40% (跌 60%)
- 沉睡：9 年
- 5y max/min 2.5x，6m 滑窗最大 1.45x
- 60d 振幅 **5.5%**，60d 量 **58%** × 3y 均量

**6195 詩肯** [上櫃] — 31.9x 歷史倍數最高
- 曾 10 倍：2008-09 1.5 → 2013-11 49.2 = **31.9x**
- 跌幅：今價 23.7 = 峰值 48% (跌 52%)
- 沉睡：12.4 年 — 全名單最久
- 60d 振幅 8.5%，60d 量 73% × 3y 均量

### 限制
- Yahoo 資料對減資 (capital reduction) 的還原可能不完美 — 邊角案例需手動驗證
- 「沉睡」≠「會漲」— 工具只是過濾「有可能 turnaround 的池子」，不是買入訊號
- ABCDE 五關全過的標的數量稀少 (台股全市場每天大約 0-5 檔)，建議搭配基本面研究

---

## 環境變數

| 變數 | 用途 | 來源 |
|------|------|------|
| `TG_BOT_TOKEN` | Telegram Bot 推送 | `~/.claude/channels/telegram/.env` |
| `FINMIND_TOKEN` | FinMind API | 個人 token |

---

## 檔案位置總覽

```
~/project/tw_stock_tools/
├── tw_lending_monitor.py      # 借券議借 + 借券賣出減少監控（每日排程）
├── tw_lending_lookup.py       # 單檔借券查詢（CLI）
├── tw_margin_monitor.py       # 融資維持率全市場掃描（含 cohort 分布）
├── tw_margin_lookup.py        # 單檔融資維持率 + cohort 分析（CLI）
├── bsr_scraper.py             # TWSE BSR 爬蟲（ddddocr 解 CAPTCHA）
├── tpex_scraper.py            # TPEx 分點爬蟲（patchright + Xvfb 解 Turnstile）
├── tw_broker_monitor.py       # 分點+融資連動分析全市場掃描（每日排程）
├── tw_broker_lookup.py        # 單檔分點+融資連動分析（CLI，需 BSR 累積 ≥2 天）
├── tw_broker_history_lookup.py # 個股 N 天累積分點查詢（HiStock 爬蟲，CLI）
├── tw_us_correlation.py       # 台股 ↔ 美股 peer 相關性查詢（CLI，β 調整 / 全市場掃描）
├── tw_turnaround_screener.py  # Turnaround 篩選（毛利率↑+量能↑+借券↓，CLI）
├── tw_limitup_signal.py       # ABCD 接力型訊號分析（standalone 漲停掃描 / Layer 2 用）
├── tw_daily_screen.py         # 每日兩層篩選工作流（Layer 1 + Layer 2，19:00 cron）
├── tw_dormant_giants.py       # 沉睡巨人篩選器（曾 10x / 跌 ≥50% / 沉睡 ≥5y / 量縮整理）
├── dormant_cache/             # Yahoo 18y 還原股價快取（git ignore，cache 7 天）
├── screener_cache/            # FinMind 季報 + 借券餘額快取（git ignore）
├── limitup_cache/             # 漲停訊號工具快取（市場/個股/SBL/HiStock，git ignore）
├── concept_momentum/          # 概念動能子模組（詳見內部 README.md）
├── margin_cache/              # FinMind 融資快取（git ignore）
│   └── finmind_{code}_{date}.json
├── bsr_cache/                 # BSR 分點 cache（git ignore）
│   └── {code}_{date}.json
├── lending_monitor.log        # 排程 log（git ignore）
├── broker_monitor.log         # 排程 log（git ignore）
├── README.md                  # 本文件
└── .gitignore
```

---

## 資料源文件

### TWSE 公開 API
- `t13sa710`：SBL 借券交易（上市+上櫃）
  - `https://www.twse.com.tw/SBL/t13sa710?startDate=YYYYMMDD&endDate=YYYYMMDD&stockNo=CODE&response=json`
- `t13sa870`：SBL 還券明細
  - `https://www.twse.com.tw/SBL/t13sa870?startDate=YYYYMMDD&endDate=YYYYMMDD&stockNo=CODE&response=json`
- `TWT93U`：信用額度總量管制（含借券賣出餘額）
  - `https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=YYYYMMDD&response=json`
- `MI_MARGN` (OpenAPI 版本，不被反爬)：今日融資融券餘額
  - `https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN`

### TPEx 公開 API
- 上櫃借券賣出餘額：`https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=YYYY/MM/DD&response=json`
- 上櫃融資（OpenAPI）：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance`

### TWSE BSR 分點（需 CAPTCHA）
- 入口：`https://bsr.twse.com.tw/bshtm/bsMenu.aspx`
- 5 碼英數圖形 CAPTCHA，用 ddddocr 解
- 必須帶 `__VIEWSTATE`、`__VIEWSTATEGENERATOR`、`__EVENTVALIDATION` 三個 hidden 欄位
- POST 後從回應抓 `HyperLink_DownloadCSV` 連結，下載 CSV（cp950 編碼）
- 只有當日資料

### TPEx 分點（需 Cloudflare Turnstile）
- 入口：`https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html`
- Cloudflare Turnstile 自動解鎖：必須用 patchright + Xvfb（headed mode）
- 點擊 CSV 下載按鈕取得完整資料（cp950 編碼）

### FinMind
- 融資融券歷史：`TaiwanStockMarginPurchaseShortSale`（免費版可用）
- 分點交易：`TaiwanStockTradingDailyReport`（贊助版）
- 個股基本資料：`TaiwanStockInfo`（免費版可用）
- 單檔查詢需要 data_id，`start_date` 和 `end_date`
- 免費版 600 req/hr

### Yahoo Finance
- 歷史價格：`https://query1.finance.yahoo.com/v8/finance/chart/{code}.TW?interval=1d&range=3mo`
- 上櫃用 `.TWO` 後綴
- 加權指數用 `^TWII`

### TWSE ISIN（中文名對照）
- 上市：`https://isin.twse.com.tw/isin/C_public.jsp?strMode=2`
- 上櫃：`https://isin.twse.com.tw/isin/C_public.jsp?strMode=4`
- HTML 頁面，**用 `cp950` 解碼**（不要用 `big5`，會丟失字如「碁」）

---

## 部署需求

### 系統套件
```bash
# 基本
sudo apt install xvfb libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
                 libatk-bridge2.0-0 libcups2 libxcomposite1 libxdamage1 \
                 libxfixes3 libxrandr2 libgbm1 libxkbcommon0 \
                 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0
```

### Python 套件
```bash
pip install requests beautifulsoup4 ddddocr patchright matplotlib plotly flask
python3 -m patchright install chromium
```

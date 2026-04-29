# 台股借券 / 融資 / 籌碼 / 概念動能分析工具組

九大功能：

1. 借券議借異常監控（每日排程推送）→ `tw_lending_monitor.py`
2. 借券賣出餘額大幅減少監控（每日排程推送）→ `tw_lending_monitor.py`
3. 單檔借券狀況查詢（CLI）→ `tw_lending_lookup.py`
4. 融資維持率預警全市場掃描（含批次分布）→ `tw_margin_monitor.py`
5. 單檔融資維持率估算 + 批次 cohort 分析（CLI）→ `tw_margin_lookup.py`
6. **分點+融資連動分析（每日排程推送）** → `tw_broker_monitor.py` / `tw_broker_lookup.py`
7. **概念動能監控 + Rerating 偵測（每日排程推送 PNG + 網頁儀表板）** → `concept_momentum/`
8. **台股 ↔ 美股 peer 相關性查詢（CLI）** → `tw_us_correlation.py`
9. **Turnaround 篩選器（毛利率改善 + 量能放大 + 借券回補）** → `tw_turnaround_screener.py`

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
| `--vol-ratio` | 1.3 | 近 20 日均量 / 近 60 日均量 ≥ N |
| `--sbl-decline` | 0.95 | 近 10 日借券賣出餘額均 / 前 30 日均 ≤ N |

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
# 預設掃描 concepts.json (~190 檔)
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py

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

### 實例（2026-04-29 跑出 7 檔）
3105 穩懋 GM 16.7→31.8% / Vol 1.30x / SBL -10.9%（融券 +94% — 散戶仍在空）
6173 信昌電 GM 22.3→26.8% / Vol 1.62x / SBL -26.3%
3491 昇達科 GM 50.6→58.6% / Vol 1.55x / SBL -16.2%
4576 大銀微 GM 35.8→38.4% / Vol 1.64x / SBL -47.5%（融券 +246% — 對立明顯）
3406 玉晶光 GM 30.9→34.3% / Vol 1.56x / SBL -31.3%（融券也 -85%，最乾淨訊號）
6166 凌華 GM 34.5→36.7% / Vol 1.96x / SBL -5.7%
2314 台揚 GM -7.4→2.9% / Vol 1.35x / SBL 0%（流動性過低，待驗）

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
├── screener_cache/            # FinMind 季報 + 借券餘額快取（git ignore）
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

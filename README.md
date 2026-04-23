# 台股借券 / 融資分析工具組

四支 Python 腳本（純標準庫 + FinMind + Yahoo Finance），涵蓋：

1. 借券議借異常監控（每日排程推送）
2. 借券賣出餘額大幅減少監控（每日排程推送）
3. 單檔借券狀況查詢（CLI）
4. 融資維持率預警全市場掃描
5. 單檔融資維持率估算（CLI）

所有腳本放在 `~/project/tw_stock_tools/`，cron 設定每天排程推送到 Telegram 群組。

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

## 4. `tw_margin_lookup.py` — 單檔融資維持率查詢

### 用途
輸入股票代號，立刻算出估算維持率、警戒價、追繳價、近期融資買進明細。

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

## 環境變數

| 變數 | 用途 | 來源 |
|------|------|------|
| `TG_BOT_TOKEN` | Telegram Bot 推送 | `~/.claude/channels/telegram/.env` |
| `FINMIND_TOKEN` | FinMind API | 個人 token |

---

## 檔案位置總覽

```
~/project/tw_stock_tools/
├── tw_lending_monitor.py      # 借券異常監控（議借 + 賣出減少）
├── tw_lending_lookup.py       # 單檔借券查詢
├── tw_margin_monitor.py       # 融資維持率全市場掃描
├── tw_margin_lookup.py        # 單檔融資維持率查詢
├── margin_cache/              # FinMind 快取資料夾（git ignore）
│   └── finmind_{code}_{date}.json
├── lending_monitor.log        # cron 排程執行 log（git ignore）
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

### FinMind
- 融資融券歷史：`TaiwanStockMarginPurchaseShortSale`
- 單檔查詢需要 data_id，`start_date` 和 `end_date`
- 免費版 600 req/hr

### Yahoo Finance
- 歷史價格：`https://query1.finance.yahoo.com/v8/finance/chart/{code}.TW?interval=1d&range=3mo`
- 上櫃用 `.TWO` 後綴

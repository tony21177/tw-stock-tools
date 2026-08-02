# 融資維持率工具(tw_margin_monitor / tw_margin_lookup)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

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
對每檔股票，從過去 1 年每日的融資資料重建「成本」（2026-07-30 由 3 個月改 1 年，視窗與價格同步拉長）：

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
- 1 年歷史：FinMind `TaiwanStockMarginPurchaseShortSale`（per-stock，每檔股票一次 API）
- 股價：Yahoo Finance 1 年日線（`fetch_yahoo_history(code, "1y")`，須覆蓋 FIFO 視窗，否則視窗前買進無收盤價會被丟棄）

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

**網頁版**：`/margin-lookup?code=XXXX&method=fifo|lifo|proportional`（dashboard 快速查詢列「💳 融資維持率」，2026-07-07 加；同 CLI 輸出 + 術語說明）

### 用途 (2026-07-20 改版)
輸入股票代號，輸出：
- **主指標：XQ/三竹口徑「遞迴融資成本線」**（市場資料商同款算法：`今日成本 = (昨日成本×(餘額−買進) + 收盤×買進) ÷ 餘額`，賣出以均價移除、全歷史遞迴自 2018 起）— 無「舊部位成本未知」黑洞，種子不敏感（實測 2018~2025 任一起點收斂相同）。維持率同時給**五成（券商實務，上櫃/高價股常見）與六成（法規上限，金管會歷次令上市上櫃均六成）兩口徑**＋各自追繳價 — 實際成數依券商與個股而異，真實值落在區間內
- **現價用交易所 MIS 即時報價**（盤中即時、收盤後=當日收盤；修 Yahoo 404 fallback 的 stale 價問題，來源標示在輸出）
- 第二段：FIFO 視窗成本（**近 1 年**可追蹤批次，明示非整體。2026-07-30 由 3 個月改 1 年 `FIFO_WINDOW_DAYS=365`：融資套牢常 >3 個月，3 個月視窗常讓深套部位算不出維持率(None)；價格/融資歷史皆自 2018 起、拉長視窗有足夠資料。實測 2609 陽明 3 個月→0 可追蹤批次(None)、1 年→2874 張 $50.79(近遞迴 $52.48);3231 緯創 6887→10712 張。**視窗前更舊的部位仍是黑洞 → 看遞迴成本線**）
- **批次（cohort）分布**：把融資餘額按進場日拆成多批，看不同進場價的維持率（資料商沒有的差異化視角）
- 主要批次明細（佔總餘額 ≥5% 的大量進場日）
- 教訓：改版前 headline 把「3 個月視窗批次成本」當整體維持率，3491 於 2026-07-20 跌停日顯示 180% 安全，但遞迴成本線口徑實為 131%(六成)~157%(五成) — 差一整個風險等級

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

**Legacy 概念**：1 年觀察期之前就存在的部位，因為沒有當時的成本資料，無從估算維持率。獨立顯示「舊部位 X 張」。

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
加權成本: $179.00 (FIFO 過去 1 年)
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

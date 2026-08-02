# 主力雷達(tw_broker_monitor / lookup / history)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 5. `tw_broker_monitor.py` / `tw_broker_lookup.py` — 主力雷達 (Smart-Money Radar)

策略名：**主力雷達** (盤後 18:00 cron) — 分點買賣超 + 融資連動 = 主力建倉雙確認

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
TG_BOT_TOKEN=xxx FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_broker_monitor.py --top-n 200 --telegram
```

### 掃描標的選擇

預設每天掃兩組標的的聯集：
1. **Top N 大融資餘額**（預設 200）：用 TWSE/TPEx OpenAPI 取得當日融資餘額排序前 N 檔
2. **概念動能強勢族群成分股**（過門檻 + 20 日報酬 Top N）：讀 `concept_momentum/cache/results/analysis_{today}.json`，取通過正式選股門檻（`passes_gate=true`）的族群，按 20 日報酬 (`ret_20d`) 排序，選前 N 個（預設 8）族群的成分股加入掃描範圍。舊結果檔沒有 `passes_gate` 欄位時自動 fallback 評分 ≥ 70 的邏輯。

效果：避免某檔不在融資 Top 200 但在強勢概念中的個股漏抓 BSR 快取。可用 `--no-concept-strong` 關閉、`--concept-min-score` 調整評分門檻（fallback 用）、`--concept-top-themes` 調整強勢族群數（預設 8）。

### 排程
```
0 18 * * 1-5 ... tw_broker_monitor.py --top-n 200 --telegram
```
週一到五傍晚 6:00（BSR 約 17:30 公布）累積資料並執行分析。第 5 個交易日起分析開始有效。
注意：concept_momentum cron 設在 17:00 跑，會把 `analysis_{today}.json` 存好讓 18:00 broker_monitor 讀取。

### 已知限制
1. BSR 沒有歷史，需從今日起累積
2. Cloudflare Turnstile 偶爾偵測（10-20% 失敗率，會自動重試）
3. 無法區分「分點買進」中現股 vs 融資的比例 — 只能用相關性做 inference
4. 公開資料源都沒有 per-(分點 × 現股/融資) 細項：FinMind v4/v3 完整 enum (~100 datasets) 掃過，沒有此維度的 dataset (`TaiwanStockTradingDailyReport` 不存在)。連贊助 tier 也沒有。實務替代：HiStock 有「分點融資估計」但是 inference 結果，不完全準。

### 回測（`tw_broker_radar_backtest.py`）

主力雷達靠分點 BSR，BSR 無歷史 API → 不能重算歷史訊號。改用 cron 每天存下的實際訊號輸出
(`broker_radar_history/YYYYMMDD.json`) 做事件研究：每個被點名的 (股票, 日)，量它之後 H 日報酬
vs 大盤 vs 同期隨機股票日基準 (edge)。

**v2 重點改動**：
- **進場預設隔日開盤** (`--entry next`)：訊號 18:00 才出，隔日開盤是最早可實現的進場價；
  v1 用訊號日收盤進場是理想化（不可實現）。`--entry signal` 保留理想化版本供對照。
- **date-matched 基準**：baseline 改為與事件同日期的隨機 100 股票平均超額（對齊市場狀態），
  取代 v1 的全期隨機採樣。
- **bootstrap 95% CI + t-stat**：判讀 edge 是否顯著 — CI 全正才顯著，含 0 = 不確定。

**重要告示**：
> 事件由已部署的訊號版本產生，改訊號參數（BSR 閾值、融資相關性門檻等）後歷史事件不可比。
> 累積至少半年以上歷史後再回測才有統計意義。

**CI 判讀**：
- CI 全正 = 有統計顯著 edge；CI 含 0 = 方向參考，無統計結論
- 樣本 n < 30 → CI 非常寬，結論僅供方向參考（⚠ 警語會印出）
- edge_mean 已扣除成本（0.471%）

```bash
# 跑回測（預設 next=隔日開盤）
python3 ~/project/tw_stock_tools/tw_broker_radar_backtest.py \
  --json-out concept_momentum/cache/broker_radar_backtest.json

# 查看結果
open http://localhost:5000/broker-radar-backtest
```

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

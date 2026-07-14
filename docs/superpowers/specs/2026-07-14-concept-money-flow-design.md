# 族群資金流入流出 (Concept Money Flow) — 設計文件

- 日期：2026-07-14
- 狀態：已與使用者逐段確認（指標定義／資料流／呈現三段均核可）
- 範圍：concept_momentum dashboard 新功能，追蹤 34 個主題板塊的每日資金流入流出

## 1. 目標

回答「資金正在流入／流出哪些類股族群」：

- **方向面**：三大法人淨買賣超金額，族群加總（真的有人買/賣）
- **熱度面**：族群成交金額佔全市場比重的變化（注意力輪動）
- **交叉判讀**：兩者合看，區分「真流入 / 出貨疑慮 / 低調吸收 / 退潮」

分組沿用現有 `cache/concepts.json` 主題板塊（34 個主題、194 檔不重複個股）。

**非目標**：不做官方產業類股分組；不做買賣訊號（本功能是輪動觀察工具）；不含借券/融資面（融資變化已在第二波回測驗證無鑑別力）。

## 2. 指標定義

每主題、每交易日計算：

### 法人淨流（方向面）

| 欄位 | 定義 |
|---|---|
| `inst_net_ntd` | Σ 族群內每檔（外資+投信+自營商 淨買賣股數 × 當日收盤價），單位：億 NTD |
| `foreign_net_ntd` | 外資單獨 |
| `trust_net_ntd` | 投信單獨（自營商計入總計但不單獨顯示——多為避險單，雜訊高） |
| `inst_streak` | 法人淨流入連續天數；連續流出以負數表示 |

**近似說明（必須進術語表）**：法人金額 = 淨股數 × 收盤價，為近似值（實際成交價分布在盤中）。FinMind `TaiwanStockInstitutionalInvestorsBuySell` 原始單位是股數。

FinMind name 欄位對應：`Foreign_Investor` + `Foreign_Dealer_Self` = 外資；`Investment_Trust` = 投信；`Dealer_self` + `Dealer_Hedging` = 自營。

### 成交額占比（熱度面）

| 欄位 | 定義 |
|---|---|
| `turnover_ntd` | Σ 族群內每檔成交金額（FinMind `TaiwanStockPrice.Trading_money`，精確值） |
| `mkt_share_pct` | 族群成交額 ÷ 全市場成交額 × 100。全市場 = 該日 TaiwanStockPrice 全部列的 Trading_money 加總（含非族群股） |
| `share_vs_20d` | 今日 `mkt_share_pct` − 過去 20 個交易日均值，單位百分點 (pp)。不足 20 日資料時用現有日數均值，且渲染時標註樣本不足 |

### 交叉判讀標記

| 占比變化 | 法人淨流 | 標記 | 白話 |
|---|---|---|---|
| 升 | 買 | 🔥 真流入 | 熱度升且法人真金買 |
| 升 | 賣 | ⚠ 出貨疑慮 | 熱度升但法人在倒貨（散戶接刀） |
| 降 | 買 | 🧲 低調吸收 | 沒人注意但法人默默買 |
| 降 | 賣 | ❄ 退潮 | 熱度與資金雙離開 |
| 區間內 | 任一未達門檻 | — | 不強行分類（fail-open） |

門檻常數（模組頂層，可調）：

```python
FLOW_SHARE_PP = 0.15   # |share_vs_20d| >= 0.15pp 才算占比升/降
FLOW_INST_NTD = 0.5    # |inst_net_ntd| >= 0.5 億才算法人買/賣
```

**門檻為先驗設定、未經回測驗證** — 術語表必須註明；上線累積數據後可回測校準。

## 3. 資料流與快取

### 每日流程（掛進現有 17:00 `run_daily.py`，不加新 cron）

1. 兩次 FinMind API 呼叫（單日全市場，各一次）：
   - `TaiwanStockInstitutionalInvestorsBuySell`（start=end=當日，實測回 93k 列全市場）
   - `TaiwanStockPrice`（同法，取 `Trading_money`、`close`）
2. 按 concepts.json 分組加總 → 計算第 2 節全部欄位
3. 寫 `cache/money_flow/{yyyymmdd}.json`（一天一檔，同 `market_breadth/` 模式）
4. 讀最近 60 個日檔 → 渲染分頁 HTML + 動能表兩欄 + Telegram 摘要

日檔 schema（單日）：

```json
{
  "date": "20260714",
  "market_turnover_ntd": 4.2e12,
  "themes": {
    "CPO_矽光子": {
      "inst_net_ntd": 18.3, "foreign_net_ntd": 12.1, "trust_net_ntd": 5.2,
      "turnover_ntd": 2.1e11, "mkt_share_pct": 5.0,
      "missing": ["4977"]
    }
  }
}
```

衍生欄位（`share_vs_20d`、`inst_streak`、標記、5 日累計）由讀取端從 60 個日檔現算，不落地——避免回補順序影響快取正確性。

### 回補

`concept_money_flow.py` 為可獨立執行 CLI：

```
python3 concept_money_flow.py --backfill 60   # 回補 60 個交易日（~120 次 API）
python3 concept_money_flow.py --date 20260714 # 單日
```

- 已存在的日檔跳過（resumable，中斷重跑安全）
- 交易日判定沿用 `cache/trading_calendar.json`
- 上線第一天即有完整 60 日趨勢

### 邊界情況（fail-open）

- FinMind 402/斷線 → 該日檔**不寫**、stderr warning；dashboard 顯示到最後有資料日。絕不寫空檔（遵守「never cache empty API responses」）
- 個股缺收盤價 → 該檔法人金額跳過、記入 `missing`；占比不受影響（成交額為獨立 dataset）
- 法人資料尚未發布（16:00 前手動跑）→ 明確顯示「今日法人資料尚未發布」，不顯示 0
- 一檔屬多主題 → 各主題重複計入；術語表註明「各族群占比加總會超過 100%」

## 4. 呈現

### 4a. Dashboard 新分頁「💰 族群資金流」

- 34 主題全列，預設按今日 `inst_net_ntd` 排序
- 欄：`族群｜標記｜今日法人淨流(億)｜外資(億)｜投信(億)｜5日累計(億)｜連續天數｜今日占比%｜占比vs20日均(pp)｜60日趨勢`
- 60 日趨勢 = inline SVG sparkline（法人淨流 5 日滾動累計），無外部圖表庫
- 頁尾三件套：
  1. **術語表**：`app.py _BACKTEST_GLOSSARY` 新增條目（法人淨流之股數×收盤近似、成交額占比、四象限標記含門檻數字、門檻未經回測），經 `_glossary_section(keys)` 引用
  2. **📌 使用時機與限制**：占比會因單一權值股爆量失真（例：台積電屬 CPO 名單）；法人買 ≠ 會漲，本功能是輪動觀察非買賣訊號；多主題重複計算；金額為近似值
  3. 資料時間戳
- 入口加進 `concept_charts.py` nav generator（訊號監控群組）；全站僅一個入口，不重複（含 dashboard.html 分頁列與 app.py 頁面 nav 兩處都要從 generator 出）

### 4b. 族群動能表加兩欄

現有動能排行表每列加「法人淨流(億)」「標記」，tooltip 帶完整白話解釋，標記連到 `/money-flow` 分頁。

### 4c. Telegram 每日推播

併入現有 17:00 `run_daily.py --telegram` 推播序列，新增一則文字訊息：

```
💰 族群資金流 07/14
流入 Top5：
🔥 CPO/矽光子 +18.3億(外+12.1 投+5.2) 連3日 占比+0.8pp
…
流出 Top5：
❄ 航運 -9.2億 連5日 占比-0.4pp
…
⚠ 出貨疑慮：重電（占比+0.6pp 但法人 -3.1億）
```

異常提示：任何族群 `|inst_streak| >= 5` 或標記 ⚠ 時額外列出。當日無資料（法人未發布/API 失敗）則整則不推，不推空訊息。

## 5. 模組切分

| 檔案 | 職責 |
|---|---|
| `concept_money_flow.py` | 抓取 + 計算 + 日檔存取 + CLI（不碰 HTML） |
| `concept_money_flow_renderer.py` | 純渲染：日檔列表 in → 分頁 HTML / 動能表欄位 / TG 文字 out |
| `run_daily.py` | ~15 行掛載：try/except 呼叫 + 模板變數 + TG 推播 |
| `app.py` | `/money-flow` route + 術語表條目 |
| `concept_charts.py` | nav 入口 |

## 6. 測試

`tests/test_concept_money_flow.py`：

- 計算純函式：分組加總（含法人 name 欄位對應）、占比、`share_vs_20d`（含不足 20 日）、`inst_streak`（正/負/中斷）、四象限分類（含門檻邊界值 ±0.15pp / ±0.5 億、fail-open「—」）
- 日檔 I/O：寫入/讀取 roundtrip、缺日容忍
- renderer：假日檔 → HTML 含關鍵欄位與術語；空資料 empty state；TG 文字含 Top5 與 ⚠ 段
- 不打真 API：fetch 層薄，測試用假 JSON fixture

## 7. 其他慣例遵循

- README 同步更新（功能說明 + 回補指令 + 欄位解釋）
- cron 不新增；既有 17:00 cron line 已帶 FINMIND_TOKEN
- app.py / renderer 改動後 `systemctl --user restart concept-dashboard.service`
- 分頁 tab 內容由 run_daily 烤進 dashboard.html —— tab 版當日 17:00 後才可見，`/money-flow` 獨立頁即時可見（兩者都做，同盤前訊號模式）

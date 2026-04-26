# 台股概念動能監控 (concept_momentum)

用於判斷台股哪些「概念股板塊」具有持續性動能（而非事件型單日噴出）。

---

## 為什麼需要這個

單純看「今日漲幅排行」容易被事件型利多/單一領漲股誤導。真正「資金持續流入、具延續性的族群」通常呈現：
1. 族群內有**廣泛的個股參與**（broad participation，不是只有 1-2 檔撐盤）
2. **量能持續放大**（不是單日放量後退潮）
3. **連續站上短線均線**（動能沒中斷）
4. **相對大盤強勢**（資金從大盤流向這個族群）

本工具把這些條件**量化**成一個 0-100 的永續性評分，每日計算一次並推送。

---

## 指標與評分公式

| 指標 | 定義 | 標準化區間 |
|------|------|----------|
| 廣度 Breadth | 族群內過去 5d/20d 上漲股票 % | 50% → 0 分, 80% → 100 分 |
| 持續性 Duration | 族群指數連續站上 5MA 天數 | 0 天 → 0 分, 10 天 → 100 分 |
| 量能 Volume | 族群 5 日均量 / 20 日均量 | 1.0x → 0 分, 2.0x → 100 分 |
| 相對強度 RS | 族群 20d 報酬 − 大盤 20d 報酬 | -5% → 0 分, +15% → 100 分 |

**綜合評分**：
```
Score = 0.40 × 廣度 + 0.20 × 量能 + 0.20 × RS + 0.20 × 持續性
```

分級：
- ≥70（紅色）：高動能，資金持續流入
- 50-70（橘色）：中等動能
- <30（藍色）：弱勢，資金流出

---

## 檔案結構

```
concept_momentum/
├── cache/
│   ├── concepts.json     # 概念股 → 成分股對照表（可手動編輯，每季更新）
│   ├── stock_names.json  # TWSE ISIN 中文名快取（每週自動更新）
│   ├── prices/           # Yahoo Finance 快取（每日一次）
│   ├── taiex.json        # 加權指數快取
│   └── results/          # 每日分析結果 JSON
├── static/
│   ├── concept_momentum_{date}.png   # 每日快照 PNG
│   ├── concept_trend_{date}.png      # 3 個月趨勢 PNG
│   └── latest.png        # 最新 PNG
├── templates/
│   └── dashboard.html    # 互動網頁儀表板
├── data_fetcher.py       # Yahoo OHLCV 抓取
├── stock_names.py        # TWSE ISIN 中文名解析
├── concept_momentum.py   # 動能指標 + 評分歷史
├── concept_charts.py     # PNG + 互動 HTML 生成
├── rerating_detector.py  # 跨概念 rerating 偵測（β 調整）
├── run_daily.py          # 每日 orchestrator
├── app.py                # Flask 本機 server
└── README.md
```

---

## 使用方式

### 手動跑一次完整分析（抓資料 + 分析 + 圖）
```bash
cd ~/project/tw_stock_tools/concept_momentum
python3 run_daily.py
```

### 只重跑分析（用現有快取）
```bash
python3 run_daily.py --skip-fetch
```

### 推送到 Telegram
```bash
TG_BOT_TOKEN=xxx python3 run_daily.py --telegram
```

### 開啟互動網頁
```bash
python3 app.py
# 瀏覽器開 http://localhost:5000/
```

### 編輯概念股名單
直接改 `cache/concepts.json`，新增/刪除主題或調整成分股。格式：
```json
{
  "themes": {
    "主題名稱": {
      "name_zh": "中文名",
      "name_en": "English name",
      "stocks": ["2330", "2317", ...]
    }
  }
}
```
**建議每季人工更新一次**（新熱點、失效概念）。

---

## 排程

cron 設定：每週一到五下午 5:00 自動跑，PNG + 文字摘要推送到 Telegram 群組。

```
0 17 * * 1-5 TG_BOT_TOKEN=... /usr/bin/python3 /home/kun/project/tw_stock_tools/concept_momentum/run_daily.py --telegram >> /home/kun/project/tw_stock_tools/concept_momentum/daily.log 2>&1
```

---

## 資料來源

- **Yahoo Finance**：個股 3 個月日線（OHLCV）
- **Yahoo Finance ^TWII**：加權指數（相對強度基準）
- **概念股名單**：手動維護 JSON，基於公開媒體（StockFeel、商周、Sinotrade 等）整理

**為何不用爬蟲動態抓**：
- Goodinfo 概念股頁面需要會員登入才能看完整清單
- Statementdog 有 tag ID 但需爬取且反爬嚴格
- 手動維護反而比較穩定，代價是需要每季更新名單

---

## 目前覆蓋的概念（28 個）

CPO/矽光子、AI伺服器、ASIC自研晶片、玻璃基板/TGV、先進封裝/CoWoS、HBM記憶體、液冷散熱、重電/電網、軍工、機器人、無人機、鋰電池/儲能、PCB/ABF載板、矽智財/IP、量子運算、低軌衛星、CXO/生技代工、網通/5G、ADAS/智駕、綠能/太陽能、蘋果概念、車用電子、被動元件、Edge AI、折疊螢幕、電動車/EV、半導體設備、光學鏡頭。

覆蓋約 190 檔股票（去重後），涵蓋台股當前熱門板塊。

---

## Rerating 偵測（rerating_detector.py）

### 核心問題
公司業務常常會擴展到新領域（例如傳統電子廠跨入 AI 伺服器），但「概念股名單」通常落後 1-2 季。市場其實已開始重新評價（rerate），但分類沒跟上。

我們用 **股價走勢** 抓這個訊號：如果某檔股票過去 60 個交易日的走勢與「自己被分類的概念」相關性低，反而與「另一個概念」相關性高，就疑似 rerating。

### 核心演算法

**Step 1：β 調整 excess returns**
```
β = cov(stock_return, TAIEX_return) / var(TAIEX_return)
excess_return(t) = stock_return(t) - β × TAIEX_return(t)
```
為什麼要扣大盤 β？台股有「萬有引力」效應，台積電（β≈1.0）跟所有東西都相關，因為它本身就是大盤代理。扣掉大盤共動後，剩下的 excess return 才反映「個股獨立的價格行為」。

**Step 2：過濾大型權值股（萬有引力過濾器）**
```
若 corr(stock, TAIEX) > 0.85 → 跳過該股
```
這把台積電、鴻海、台達電等大盤代理股排除。它們無論扣不扣 β 都會跟很多概念高相關，rerating 訊號毫無意義。

**Step 3：對每個概念建立 excess return 序列**
- 對每個概念做等權重指數（已在 concept_momentum.py 實作）
- 同樣扣除大盤 β，得到概念的 excess return 序列

**Step 4：算個股 vs 每個概念的 excess return Pearson 相關**
- 取最近 60 個交易日（約 1 季）
- 對每一檔股票，計算它與所有 28 個概念的相關係數

**Step 5：計算 Rerating 分數**
```
own_max_corr = 該股原屬概念中相關性最高者
top_other_corr = 該股不屬於的其他概念中相關性最高者
rerating_score = top_other_corr - own_max_corr

若 rerating_score > 0.15 → 列入「疑似 rerating」名單
```

### 為什麼用 60 天視窗
- 太短（如 20 天）：訊號雜訊高，容易被短期波動誤判
- 太長（如 250 天）：rerating 是「相位變化」，長期平均後變平淡看不到變化
- 60 天 ≈ 1 季，恰好對應市場法人重新分類的週期

### 輸出範例
```
2354 鴻準 [上市]
  原屬：蘋果概念 (excess corr +0.09)
  →更接近：ADAS / 智駕 (excess corr +0.52)
  Rerating 分數：+0.42  (TAIEX β corr 0.77)
```
解讀：鴻準近 1 季扣除大盤後，跟 ADAS/智駕概念股的走勢相關性（+0.52）顯著高於跟蘋果概念（+0.09），可能反映業務從消費電子轉向汽車電子。

### 限制
- 只是「相關性」訊號，不是因果。需搭配公司財報/法說會驗證
- 60 天的相關係數仍可能受短期事件影響
- 等權重概念指數可能被特定大型股主導
- 沒考慮類股輪動，只看時間序列相似度

---

## 已知限制

1. **名單會過期**：熱門概念每季變動，需手動維護 `concepts.json`
2. **等權重計算**：族群指數用等權重，大型股（如 2330）和小型股被同等看待
3. **成分股重疊**：台積電同時在 CPO、先進封裝、蘋果概念 → 各族群會有相關性
4. **Yahoo 偶爾 rate limit**：4-5 檔股票可能跳過（不影響族群平均）
5. **短期指標**：只看 5d/20d，長線（半年/一年）動能另議
6. **不含基本面**：純技術面指標，沒有考慮營收/EPS/本益比

---

## 典型解讀

**高評分 + 高廣度 + 高量能 + 持續天數多**：資金持續散進，延續性高，進場風險相對低。
**高 20d 報酬 + 低持續天數**：單日爆衝型，可能是事件利多，延續性低，不建議追高。
**低廣度 + 高漲幅**：只有領漲股在漲，族群效應不明顯。
**RS 正、但量比 <1**：表示強於大盤但量能退縮，可能是短暫補漲。

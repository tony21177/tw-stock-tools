# 林則行矩陣選股 — 設計文件

**日期**：2026-07-25
**狀態**：設計已核准，待實作

## 一句話

掃全市場個股近 6 個月日 K，偵測林則行「低量箱型矩陣」，輸出①今日爆量突破訊號 ②盤整中觀察名單 ③堆疊層數；網頁分頁 + 詳細策略說明 + 每交易日推播睏霸數錢 & 田尾三人幫。

## 林則行矩陣定義（研究來源見末）

林則行（前阿布達比主權基金經理人、日本 K 線大師，《飆股的長相》）純技術面選股法。「矩陣」= 長期低量箱型盤整後爆量突破：
- **盤整時間**：通常 3-6 個月低量橫向盤整
- **震盪幅度**：最好 ≤15%，最大 ≤30%（(箱高−箱低)/箱低）
- **盤整量能**：低量沉澱（盤整期量 < 長期均量）
- **突破量能**：突破當天量 = 月均量 2-5 倍（不超過 10 倍）
- **天花板/地板**：區間高/低，每次觸及被賣/被接
- **多重矩陣堆疊**：突破後更高位再形成新矩陣，層層過濾 = 大飆股相（鈊象三層）

## 元件

### `lin_matrix.py`（新模組，repo root）

- `build_price_series(end_date, days, token) -> dict`：FinMind 全市場日 K「單日全市場查詢 × N 天」→ `{code: [{date, open, high, low, close, volume}...]}`（依日升冪）。⚠ 全市場查詢單日一次（whole-market 範圍查詢只回第一天的 quirk，逐日查）；快取 `cache/lin_matrix_prices/{date}.json` 每日一檔，只補新日。只留 4 位數普通股。
- `detect_matrix(series, as_of_idx=-1, min_days=60, max_days=130, amp_max=0.30) -> dict|None`：對單股序列，從 as_of 往回找**最長的低量箱型**：
  - 窗口 [i, end]，end = as_of；i 由 end−min_days 往前擴到 end−max_days
  - 條件：`(max_high−min_low)/min_low ≤ amp_max` 且 `窗口均量 < 窗口前段(或全序列)均量 × VOL_SETTLE_RATIO`
  - 取滿足條件的最長窗口 → 回 `{start, end, days, floor(=min_low), ceiling(=max_high), amp_pct, box_avg_vol, tier}`；tier = "⭐" if amp≤0.15 else "☆"；無則 None
- `classify(series, matrix, today) -> dict`：
  - `breakout`：今日收盤 > ceiling 且 今日量/box_avg_vol ∈ [BREAK_VOL_MIN=2, BREAK_VOL_MAX=10]
  - `in_box`：今日收盤 ∈ [floor, ceiling]，`box_pos = (close−floor)/(ceiling−floor)`；`near_ceiling = box_pos ≥ 0.8`
  - `vol_mult`：今日量 / box_avg_vol
- `count_stacked(series, top_matrix) -> int`：從最新矩陣往回，數「前一個更低位置的已突破矩陣」連續層數（每層 = 一個低量箱→爆量突破→更高箱）
- `build_signals(series_map, today) -> dict`：對每股跑 detect+classify+stack → 分三桶
  `{"breakout": [...], "watch": [...(in_box near_ceiling)], "date": today}`；每筆含 code/name/floor/ceiling/days/amp_pct/tier/box_pos/vol_mult/stack。依 vol_mult(突破)/box_pos(觀察) 排序

### 呈現

- 網頁 `/lin-matrix`（app.py route + `render_html`）：三分區（🚀今日突破 / 📦盤整中貼天花板 / 全盤整清單），每檔顯示 代號/名稱/矩陣(地板~天花板)/盤整天數/幅度級別(⭐/☆)/箱內位階%/堆疊層數/今日量倍數。**詳細策略說明區**：林則行矩陣定義、三條件表、判讀紀律、資料來源、⚠先驗未回測、非買賣訊號
- 每交易日 cron 推 **睏霸數錢(C96e49…) + 田尾三人幫(Ca0735…)**：今日突破 Top + 貼天花板觀察 Top（`format_report` 純文字，比照個股期報告的清楚欄位），存 `cache/lin_matrix_history/{date}.json`
- nav：主 dashboard 即時工具區加入口

### 參數（先驗、未回測，模組常數可調）

- `MIN_BOX_DAYS=60`、`MAX_BOX_DAYS=130`、`AMP_TIER1=0.15`、`AMP_MAX=0.30`
- `VOL_SETTLE_RATIO=0.8`（盤整期均量 < 長期均量 ×0.8 = 低量沉澱）
- `BREAK_VOL_MIN=2`、`BREAK_VOL_MAX=10`、`NEAR_CEILING=0.8`

## 排程

每交易日 15:00（收盤後日 K 出來）cron，`is_trading_day` 守門，推兩群 + 存歷史。首次需回補價格序列（~130 單日查詢建 cache）。

## 風險與 caveat

- **門檻先驗未回測**：矩陣天數/幅度/量倍數是依林則行文字設的啟發式，非回測校準；頁面/推播明示、非買賣訊號
- **假突破**：爆量突破後可能拉回（林則行原著也強調要看突破後續），本工具只標「今日突破」事件，不保證延續
- **箱型偵測歧義**：同股可能有多種箱型切法，取「最長低量窗口」為主；堆疊偵測是啟發式
- **資料量**：全市場 ~2000 股 × 130 日；單日全市場查詢建 cache、每日只補新日
- **除權息跳空**：用還原價（TaiwanStockPriceAdj）避免除息缺口偽造突破/破箱 —— 實作階段確認 FinMind 還原價可用，否則標註

## 測試

- detect_matrix：造低量箱型 fixture（驗區間/幅度/tier）、活躍高量非矩陣（排除）、幅度超 30%（排除）
- classify：突破（收盤破頂+量2-10倍）、量不足不算突破、in_box 位階與 near_ceiling、量>10倍不算（避免異常）
- count_stacked：三層堆疊 fixture
- build_signals：分三桶、排序
- render_html/format_report：三分區、說明區、標記
- 全 offline（mock FinMind/fixture 序列）

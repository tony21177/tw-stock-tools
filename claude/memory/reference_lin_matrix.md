---
name: reference-lin-matrix
description: 林則行矩陣選股 /lin-matrix — 低量箱型盤整→爆量突破+堆疊偵測；每交易日15:00推睏霸數錢+田尾三人幫
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

林則行矩陣選股(2026-07-25 加，brainstorm→spec→實作)：

## 策略(研究自 vocus 蛙蛙國教室/財訊/《飆股的長相》)
林則行=前阿布達比主權基金經理人、日本K線大師，純技術面。矩陣=長期低量橫向箱型盤整→爆量突破：
- 盤整 3-6 個月(本工具 MIN_BOX_DAYS=60、MAX=130)、震盪幅度 **≤15% 嚴格**(2026-07-25 由 ☆≤30% 收緊；AMP_MAX=0.15，寬箱如旭富26.8%/櫻花建25.7%已剔除，全為 ⭐)、盤整期低量沉澱(箱均量 < 之前250日均量×0.8)、突破當天量=箱型均量 2-10 倍(BREAK_VOL_MIN/MAX)
- 天花板=箱型區間高、地板=區間低；多重矩陣堆疊(突破後更高位再形成新箱)=大飆股相(鈊象三層)

## 模組 `lin_matrix.py`(repo root)
- `detect_matrix(series, as_of_idx, ...)`：從 as_of 往回找最長低量箱(取最長符合窗口)。⚠ 低量基準用箱型「之前250日」均量(非緊鄰同長度，否則堆疊時緊鄰是低箱會誤判)
- `classify`：breakout(收破頂+量2-10倍)/in_box/box_pos/near_ceiling(≥0.8)
- `count_stacked`：從最新矩陣往回數連續「天花板更低的已突破箱」層數
- `build_signals`：⚠ 偵測矩陣用 as_of_idx=len-2(排除今日突破日，否則天花板被拉高)→分三桶 breakout/watch/boxed
- `build_price_series`：全市場單日×N天(逐日快取 `cache/lin_matrix_prices/{date}.json`，只補新日)。⚠ FinMind 全市場範圍查詢只回第一天→逐日查
- `render_html`(含策略說明區 `_STRATEGY_NOTE`)、`format_report`
- 每檔含**盤整期平均 ATR**(True Range 均值 + 佔股價%,量化低量波動;2026-07-25 加)
- `stock_futures_codes()`：接 tw_stock_futures.fetch_taifex_mapping 取有個股期的股票代號集合,build_signals 標 `has_fut`,報告/網頁標 **📈期**(2026-07-25 加)
- **`_shape_ok(win)` 形狀閘(2026-07-25 加,回應用戶連續兩張圖「3045 台灣大山形」「5403 中菲深V」不像矩陣)**:光靠幅度≤15%+低量會收進山形/V谷/趨勢/崩跌/暴衝假箱。5 條(皆收盤價):①上下緣25%帶各觸及≥SHAPE_MIN_EDGE_TOUCH(2)②無山頭/V谷(對稱)|中段均收−兩端均收|/帶寬 ≤ SHAPE_MAX_HUMP(0.20)③非趨勢 |淨漂移|/帶寬 ≤ SHAPE_MAX_DRIFT(0.45)④單日收盤變動 ≤ SHAPE_MAX_DAILY_MOVE(0.06,擋暴衝/流動性差/崩跌)⑤盤末最大跌幅/帶寬 ≤ SHAPE_MAX_END_DROP(0.50,擋崩跌懸崖)。**關鍵方法論:用 matplotlib 把通過的箱畫成總覽圖、Read 圖親眼審計**(scratchpad/plot_boxes.py),逐張校準門檻。教訓:山形分數要對稱(V谷跟山頭一樣壞,原本只擋正值放行V是錯的);單一指標都有洞(緊箱在中間震盪→swings反而低;3045日K其實平緩→ATR分不出);sandbox 43檔候選僅16檔真箱。⚠ 純啟發式門檻、對63天資料肉眼調的,易 overfit,真環境要重校

## 回測結論(2026-07-25,tw_lin_matrix_backtest.py)
用 v2 面板 bt_cache/backtest_prices_v2.json(1887檔個股・2025-01~2026-07,含還原價)做事件研究:重用 detect_matrix/classify 餵 high=low=close(面板無high/low→收盤口徑)、隔日開盤進場、還原價計酬扣成本、超額=個股−TAIEX、matched_baseline當edge、dedup_cooldown去重、60日新高必要條件預篩加速(~3分鐘)。**突破買進持有 5/10/20 日顯著跑輸大盤:超額 −0.85%/−1.38%/−3.54%,t=−2.4~−4.9,IS(2025)/OOS(2026H1)皆負,贏大盤僅27-39%。** 形狀閘讓箱乾淨(episodes 468→444)但 edge 幾乎沒動→負期望對箱品質穩健。**結論同權證工具:當觀察/選股篩子可,當進場買訊號不行;頁面已紅字揭露。**

## 上線
- 網頁 `/lin-matrix`(app.py route，優先讀當日 JSON 歷史快、無則即時算)+ 主 dashboard 即時工具 nav
- **每交易日 15:00 cron** 推睏霸數錢(C96e49)+田尾三人幫(Ca0735)+存 `cache/lin_matrix_history/{date}.json`
- ⚠ 門檻先驗未回測、非買賣訊號、假突破需看後續

## sandbox 限制
taiex.json 僅 63 交易日歷史 → 箱型只到~60日(剛好門檻)、無堆疊。真實環境完整歷史會找更長箱+堆疊。2026-07-24 首跑：旭富爆量突破、11檔貼天花板

相關：[[reference-stock-futures-ranking]]、[[reference-warrant-signal]]、[[feedback-futures-basis-dividend]]

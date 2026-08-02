---
name: reference-warrant-signal
description: 權證量能觀察 /warrant-signal — TWSE 六類權證抓取+按標的彙總+爆量×失衡訊號；回測無 edge 但依使用者決定當觀察工具上線
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

權證量能訊號策略（2026-07-21~22，brainstorm→spec→plan→SDD 完整流程）：

## 結論先講：回測無 edge，但當觀察工具上線（使用者決定）
63 交易日回測（2026-04-21~07-21）：
- **空方（大跌）從未觸發**：認售權證量僅認購 ~8%，認購佔比幾乎恆 1.0、Δ 極少跌破 −0.10（結構性、與 spec 事前風險一致）
- **多方（大漲）無 edge**：surge2 各 horizon t≈0、95% CI 全跨 0；**收緊 surge≥3 反而顯著為負**（CI[−7.68,−0.24]）→ 權證大爆量常是券商分銷/散戶追高的造市 confound，非聰明錢
- 使用者決定「合併 main 保留工具、照常上線、只在回測頁面說明」→ 當觀察工具上線，頁面紅字揭露無 edge

## 資料源（重要，FinMind 無權證）
- TWSE `MI_INDEX?type=<T>&response=json&date=YYYYMMDD` 六類：`0999`認購/`0999C`牛證/`0999X`可展延牛（偏多）、`0999P`認售/`0999B`熊證/`0999Y`可展延熊（偏空）。每筆含標的代號+名稱+收盤（權證→現股對應）。認購 ~27k 筆/日、認售僅 ~2k
- 履約價/到期日不在成交資料裡 → **元大權證網 API**：`POST https://www.warrantwin.com.tw/eyuanta/ws/GetWarData.ashx`，body=`data=`+URL-encoded JSON（factor.columns 選 `FLD_N_STRIKE_PRC`履約價/`FLD_DUR_END`到期/`FLD_LAST_TXN`最後交易/`FLD_N_UND_CONVER`行使比例/`FLD_ISSUE_AGT_ID`券商，condition 用 `FLD_WAR_ID` 權證代號 list），**回 gzip、任何券商權證都查得到**（不限元大）。條款靜態 → `warrant_flow.ensure_terms` 增量存 `cache/warrant_terms.json`。curl 在此環境連得到 warrantwin（Google/Goodinfo/揭露平台都連不到）。這 API URL 由 user 從瀏覽器 Network tab 提供
- 發行券商從權證名稱解析（strip 標的名前綴後比對，避免金控標的誤判如「元大金富邦...」）；價內外 = 現股收盤(日檔 close，來自 MI_INDEX 標的收盤價欄) vs 履約價

## 模組（都在 concept_momentum/）
- `warrant_flow.py`：`fetch_warrant_day`(六類)、`aggregate_by_underlying`(按標的 bull/bear turnover+issuers+top_warrants)、`run_day`(日檔，空日不寫防限流破洞)、`--backfill N`/`--date` CLI
- `warrant_signal.py`：`build_signal_rows` 爆量倍數(今日總額÷近20日均)×認購佔比 Δ(vs 自身20d,非絕對0.5)→ bull/bear/neutral；`MIN_HISTORY=10` 最低歷史門檻
- `warrant_signal_backtest.py`：`evaluate` 無前視事件研究(window=day_files[:end])、`forward_return`、`_stats`(含 t-stat+CI95)、`sweep` 參數掃描、FinMind CLI
- `warrant_signal_renderer.py` + app.py `/warrant-signal` route + 18:30 每日 cron

## 自動化
- 18:30 平日 cron：`warrant_flow.py --date $(date +%Y%m%d)` 累積日檔（權證 EOD 已公布）
- `cache/warrant_flow/{date}.json` 逐日累積；`cache/warrant_backtest.json` 回測結果（頁面讀取顯示揭露）
- 無 LINE/TG 推播（無 edge、不推雜訊）

## 未來若要再驗證
taiex.json 歷史只到 63 天限制樣本；累積更長日檔後、或改良訊號（限特定隱波/價內外/發行券商條件）可用 `warrant_signal_backtest.py --backfill-days N` 重跑

相關：[[reference-money-flow]]（同為先驗未回測觀察工具）、[[reference-chip-episode-compare]]

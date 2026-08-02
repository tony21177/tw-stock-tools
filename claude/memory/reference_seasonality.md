---
name: reference-seasonality
description: 月份季節性/月曆效應 /seasonality — 指數月份勝率+漲停家數月份統計;tw_seasonality.py;每月1號cron
metadata: 
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

月份季節性 (月曆效應)(2026-07-30 加,`tw_seasonality.py` · `/seasonality`):

## 用途
統計月份慣性(元月效應、農曆年作夢行情、Sell in May、紅色十月)。用戶原話「統計月份漲停,包括美股台股,看有沒有慣性」→ 美股無漲停制度故做「指數月份季節性」+ 台股「漲停家數月份」兩塊。

## A. 指數月份季節性
- 標的:加權/S&P500/Nasdaq/費半/道瓊(**Yahoo 月線** `interval=1mo&range=25y`,回到 2001-08)+ 櫃買 OTC(FinMind `TaiwanStockPrice` **data_id=TPEx** 有 open/max/min/close 價格指數)+ 台指期近月連續(FinMind `TaiwanFuturesDaily` TX,trading_session=='position',每日取近月=最小 contract_date≥當月、月末收盤)。
- 每日曆月(1-12)算:上漲勝率/平均/中位報酬/標準差/最佳年/最差年。勝率≥65% 標紅=強慣性、≤35% 標綠。**當月未收月自動剔除**(monthly_returns 濾掉 cur_ym)。
- FinMind `TaiwanStockPrice` **data_id=TAIEX** 也能直接拿加權價格指數(回到 2004),但加權用 Yahoo ^TWII(乾淨 25 年)。
- 三視圖:①跨指數月平均報酬熱力表 ②各指數詳細季節表 ③加權&S&P 年×月矩陣。
- 驗證合理:S&P 強月 4/5/7/11、費半 5 月 avg+4.58%、加權強月 2/10/12(農曆年+年底作夢)。

## B. 台股漲停/跌停家數月份(投機熱度季節性)
- FinMind **`TaiwanStockPriceAdj`** 全市場單日查(~2500 檔,**不含權證**;raw `TaiwanStockPrice` 全市場含 5 萬+權證會污染,勿用)。**4 位數普通股過濾** `_is_common`:len==4 & isdigit & 首碼≠'0'(排除 6+位權證、00開頭 ETF、帶字母特別股/TDR)。
- 每日 pct=spread/(close-spread)*100;漲停 pct≥9.5、跌停≤-9.5。按日曆月聚合「日均家數」+漲跌停比。
- ⚠ **台股漲跌幅 2015-06 由 7%→10%,跨制度家數不可比,故只算 2015-06 起**(LIMITUP_START)。
- 逐日快取 `cache/season_limitup/{date}.json`={lu,ld,n}。首建 `--backfill-limitup` 補 2015-06 起~2724 交易日(~40 分背景,可重跑跳過已快取,partial 也能算)。交易日曆自 TAIEX 日線取。

## 上線
- 模組函式:`_yahoo_monthly`/`_finmind_index_monthly`/`_tx_monthly`/`monthly_returns`/`seasonality_stats`/`year_month_matrix`/`_limitup_day`/`backfill_limitup`/`aggregate_limitup`/`build`/`render_html`。結果 `cache/seasonality_latest.json`(JSON 後 month/year 變 str key,render 用 `.get(str(m),.get(m))` 兼容)。
- 顏色遵**台股慣例 紅=漲綠=跌**(`_heat`:正→紅、負→綠)。
- app.py route `/seasonality` 讀 cache fallback build();首頁 nav 📅 月份季節性(concept_charts.py + dashboard.html)。
- **每月 1 號 06:15 cron**:先 `--backfill-limitup`(增量補新交易日)再 `--build`;不推播(季節性慢、且 LINE 額度)。
- CLI `--build`/`--backfill-limitup [--start]`/`--html`。
- ⚠ 季節性≠必然(近年結構升息/AI/被動資金可能改月曆效應),非買賣訊號。
相關:[[reference-extremes]]、[[reference-margin-scan]]、[[reference-market-overnight]]

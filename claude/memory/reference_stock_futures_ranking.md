---
name: reference-stock-futures-ranking
description: 個股期火熱排行 /stock-futures — 全市場個股期按成交量排名+熱門標記；每交易日15:30推睏霸數錢
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

個股期(股票期貨)火熱排行(2026-07-24 加，比照群益「個股期火熱排行」圖)：

## 模組 `tw_stock_futures.py`(repo root)
- `fetch_taifex_mapping`：TAIFEX `www.taifex.com.tw/cht/2/stockLists` HTML 表 → {2字母期貨前綴: {stock, name, is_fut}}，快取 `cache/stock_futures_map.json`。CC→聯電2303、QF→台積電2330(小型)、CD→台積電、DX→緯創。310 筆對照
- `fetch_ranking(date, top_n)`：抓當日+前日全市場 `TaiwanFuturesDaily` → `build_ranking`。⚠ **FinMind 全市場範圍查詢只回第一天(quirk)→ 必須兩次單日查**
- `build_ranking`：對照標的(排除指數期/is_fut=False)、跨契約月加總量+未平倉、近月日盤取收盤/漲跌幅/高低、依成交量降冪。標記：f_pct_top(|漲跌幅|前10)、f_rank_jump(成交量排名較前日≥30名躍升)、f_range_top(日振幅(高-低)/收前20)、f_hot(量前20)
- `format_report`(LINE/TG 文字)、`render_html`(網頁)

## 資料欄位(每檔個股期,17 欄,2026-07-27 大擴充)
標的股票代號+名稱、期貨代碼(fid, 3碼如CCF)、收盤、漲跌幅(spread_per)、**基差**(近月期貨−現貨,升水+/貼水−;現貨 FinMind TaiwanStockPrice)、成交量、量增減、未平倉、**週轉**(量/未平倉,高=當沖/低=佈局)、**近月倉增減**/**遠月倉增減**(拆近月[最小到期月]vs遠月[其餘加總],結算換月時部位近→遠)、**近遠價差**(次近月−近月日盤收)、**法人淨**(特定法人[前十大法人]所有契約淨留倉買−賣,**全市場~262檔逐檔**,源 TAIFEX 大額交易人未沖銷部位表 `_fetch_large_trader_net`;⚠⚠ 教訓:FinMind TaiwanFuturesInstitutionalInvestors 那23檔**全是指數期(TX/MTX/電子/金融/半導體30…)、沒有個股期**,棄用;TAIFEX「三大法人-區分各契約」把股票期貨加總成一列不逐檔;唯一逐檔=大額交易人表 largeTraderFutQry(commodityId空即回全市場1.9MB,每檔兩列:11欄近月+10欄所有契約,買十法人=paren(所有契約列idx3)、賣十法人=idx7,名稱去「期貨」對回 mapping name→stock,日快取 cache/lt_inst.json)。前十大特定法人 proxy 非完整三大法人)、**象限**(量價未平倉四象限 `_quadrant`:漲跌×總OI增減→🟥新多/🟧空補/🟩新空/🟦多結)、**距結算**(`_days_to_settle` 近月第三個週三天數)、標記。FinMind futures_id 前2碼 = TAIFEX 對照 key。
- `_agg_by_futures` 記 oi_by_cd/close_by_cd(各月);`build_ranking(...,cash_close,inst)`;`_fetch_cash_close`/`_fetch_inst_net`(fetch_ranking 多抓 2 次 FinMind → 頁面較慢)

## 網頁功能(2026-07-27)
- **17 欄全可點標題排序**(前端 `_SORT_JS`,每格 data-v 真值、NaN沉底、再點反向;象限/標記按權重分)
- **四象限圖解 `_QUAD_LEGEND`** + **各欄計算方式 `_COL_GLOSSARY`(17 欄全白話註解)**

## 上線
- 網頁 `/stock-futures`(app.py route，top 30)+ nav 連結
- **每交易日 15:30 cron**(is_trading_day 守門，期貨盤後)推睏霸數錢群組 C96e49…(Top20+標記)+ 存 `cache/stock_futures_history/{date}.json`
- ⚠ 純排行/觀察工具、非買賣訊號

## 同批
- 2026-07-24 停掉 AI 敘事推播(chip_narrative_push cron 移除)，改推這個個股期排行

相關：[[reference-warrant-signal]]、[[reference-money-flow]]

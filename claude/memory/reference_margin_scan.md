---
name: reference-margin-scan
description: 全市場融資維持率斷頭掃描 /margin-scan — 追繳/斷頭區<130%+邊緣130-140%;遞迴成本線;每交易日22:15重建
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

全市場融資維持率斷頭掃描(2026-07-29 加,`tw_margin_scan.py` · `/margin-scan`):

## 功能(2026-07-29 改版:用戶要「買發生大量斷頭的標的」= 反市場低接落底)
**核心指標=融資餘額大減**(斷頭/認賠強制賣出湧出),不是維持率水位!掃近 LOOKBACK=5 交易日:
- 篩:5日融資減幅 ≥ MIN_DROP_PCT=8% + 股價下跌(排除獲利了結) + 5日前餘額≥MIN_BAL=300張
- 依融資減幅% 排序;🧹清洗 = 融資減幅 > 股價跌幅(斷頭殺過頭、浮額洗掉,常見落底)
- 維持率(遞迴成本線)當 context 欄:越低=被斷部位套越深
- 2026-07-28:175 檔(銘旺科 融資-56%/維持率81%、聯電 -54,098張、南亞 -15,311張)
- ⚠ **舊版是「維持率斷頭風險警告」(躲斷頭);用戶真正要的是相反 —— 買斷頭washout。已改版。**維持率計算/遞迴成本線邏輯仍保留(當 context)。

## 方法(重用單檔工具的成本線)
- 維持率 = 現價 ÷ (遞迴融資成本線 × 融資成數) × 100%。
- **遞迴成本線** = `tw_margin_monitor.compute_recursive_cost(history, daily_prices)`(XQ/三竹口徑:今日成本=(昨成本×(餘額−買進)+收盤×買進)÷餘額;種子不敏感、近一年迭代即收斂)。history=[{date:YYYYMMDD, buy, balance}] 逐日全市場融資、daily_prices={YYYYMMDD:close}。
- 融資成數:上市(twse)RATIO_TWSE=0.6、上櫃(tpex)0.5;同列 mr6/mr5,主 mr 用市場成數(6成較保守=維持率較低=多抓)。市場別 TaiwanStockInfo `type`(twse/tpex/emerging)。

## 資料
- 全市場融資:FinMind `TaiwanStockMarginPurchaseShortSale` **逐日全市場單日查**(欄 MarginPurchaseBuy 買進、MarginPurchaseTodayBalance 餘額,單位張),快取 cache/margin_hist/{date}.json。
- 收盤:重用 `tw_extremes._day_prices`(還原 year_prices 快取,省抓取)。交易日曆 `tw_extremes._trading_dates`(2330 一年)。首建~243 天融資抓取(背景數分鐘)。結果 cache/margin_scan_latest.json。

## ⚠ caveat / 驗證
- 用**還原收盤 + EOD 收盤**估(非即時);個股維持率≠整戶維持率。這是全市場**篩選**,單檔精確用 /chip 或 tw_margin_lookup.py(原始價+交易所即時價 fetch_mis_price+FIFO)。
- **已驗證方法**:對 tw_margin_lookup 逐檔比,成本線/公式一致(元晶6443 成本47.12=47.12;耀登 151.87 vs 154.18 小差=還原vs原始)。維持率差異只來自價格日(掃描07-28收盤 vs 單檔07-29即時,今天再跌所以即時更低)。
- 還原價使成本略低→維持率略偏高(偏安全)→ 邊界可能少抓;要更保守可調 WARN。

## 上線
- 網頁 `/margin-scan`(app.py route 讀 margin_scan_latest.json)+ 首頁 nav。
- **每交易日 22:15 cron 重建 JSON**(is_trading_day 守門、FINMIND_TOKEN;**暫不推播**——LINE 每月額度2026-07已用完 + 370檔太多不適合推)。
相關:[[reference-extremes]](共用 year_prices 快取)、[[reference-chip-skill]]、[[margin_lookup 收盤後現價會 stale]]

## 融資賣壓/量% 欄(2026-07-30 加,依 vocus 文章)
`= 近5日「融資賣出」總張 ÷ LOOKBACK(5) ÷ 近5日均量 × 100%`。衡量每天融資被迫平倉賣單佔成交量比例。**關鍵:用融資「賣出」(gross,`MarginPurchaseSell`)不用餘額淨變動** —— 淨變動被當日融資買進沖抵會低估真實斷頭賣壓(文章環球晶例:淨減看似7.7%、實際賣出佔量14.9%);現金償還不上量不計入。**>15%(紅)=賣單佔量1/5、常伴連續跌停=系統性斷頭鐵證;10-15%(橙)顯著**。
- `_margin_day` 改存 `[buy,bal,sell]`(sell=MarginPurchaseSell);舊快取 len-2,`ensure_sell=True` 時自動重抓補(只補近5日,老日不動)。主迴圈解包改 `v[0]/v[1]` 別再 `(buy,bal)` unpack(會炸)。
- `_vol_day(date,token)`:TaiwanStockPriceAdj `Trading_Volume`/1000=張,近5日逐日快取 `cache/vol_day/`。
- 驗證:2026-07-28 跑 173/175 有值,銘旺科2429 32.8%(5日融資減56%)、艾姆勒2241 30.8%,重洗盤股全紅。小型低量股(暉盛均量99張)易讀高/雜訊,tooltip 露日均賣/均量供校。
- 策略⑤系統性斷頭警訊:點此欄排序,先確認比回落+跌停打開(賣壓宣洩完)再低接。與 5日融資減% 互補(減%看餘額縮、這欄看賣壓佔量兇)。

## 借券賣出餘額增減欄(2026-07-29 加)
`_sbl_day(date,token)`:FinMind **TaiwanDailyShortSaleBalances** 全市場單日查(今/昨同列,一次搞定)→ {code:[今餘額張, 增減張]},欄 SBLShortSalesCurrentDayBalance/PreviousDayBalance(股,/1000=張),快取 cache/sbl_day/。⚠ 借券賣出(SBL)≠融券。綠(借券減=回補、空方縮手,對低接偏多)/紅(增=新空)。約21:30公布(cron 22:15 覆蓋)。融資斷頭(多投降)+借券回補(空投降)=多空雙殺洗盤更像底。

# 📊 一年高低極端榜(/extremes)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

📊 **一年高低極端榜**（`/extremes`，2026-07-28 加）— 全市場 4 位數個股(非 ETF)近一年:📉**距最高點跌幅最大 Top20**((現價−一年最高)/一年最高)+ 📈**距最低點漲幅最大 Top20**((現價−一年最低)/一年最低)。價格用 **還原價**(FinMind `TaiwanStockPriceAdj` 全市場單日、含還原 high/low/close,~2320 檔涵蓋率同未還原;除權息不會被當跌幅);一年高/低取 intraday 還原高低、現價取最新交易日還原收盤,回看 250 交易日(需≥60 日排除剛上市;**近 `ACTIVE_WITHIN`=2 交易日無成交者排除 = 停牌/下市櫃**,避免殘值假跌幅如 6883 微電能源停牌前 1.74)。名稱補 FinMind `TaiwanStockInfo`(含興櫃,TWSE ISIN 只有上市櫃)。模組 `tw_extremes.py`(`_trading_dates`/`_day_prices`/`compute_extremes`/`render_html`);逐日全市場快取 `cache/year_prices/{date}.json`(首建~243 次抓取、之後每日增量),結果 `cache/extremes_latest.json`。網頁兩表(高點日/低點日顯示 YY/MM/DD 分辨去年今年)+ 計算方式說明。**每交易日 20:00 cron**(盤後還原價齊)推睏霸數錢 + 田尾三人幫。⚠ 觀察工具非買賣訊號。CLI `--date`/`--top`/`--line-to`/`--json-out`

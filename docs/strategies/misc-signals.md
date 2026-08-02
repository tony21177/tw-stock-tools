# 🔔 其他訊號:族群點火 / 分點時段 pattern / ADR 折溢價

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

**族群點火警示** — 偵測族群評分「休眠 → 轉強」事件（昨 <3 → 今 ≥10, Δ ≥8），自動標真假機率 + 5 日後續追蹤倍率（concept_momentum 17:00 cron + dashboard 🔥 族群點火 tab，2026-05-18 加）→ `concept_momentum/run_daily.py` · `/`

**分點 N 日時段 pattern** — 給定 (股號, 分點)，自動算過去 N 日該分點在早/中/尾盤的買賣分布 + 配對 OHLC 走勢 + 6 種行為標籤（尾盤低接 / 早盤追擊 / etc）+ 可展開的專有名詞詳細解讀（2026-05-20 加）→ `broker_timing_pattern()` in `tw_chip_price.py` · `/chip-price?code=X&broker=Y`

**TSM ADR vs 2330 折溢價** — TSM (台積電 ADR) 與台股 2330 的折溢價歷史，可選區間 1 週 / 2 週 / 1 / 3 / 6 個月 / 1-10 年（預設 6 個月）。換股比例 1:5，理論價 = TSM(USD)×USD/TWD÷5，折溢價 = (理論價/2330實際價−1)。資料 Yahoo (TSM/2330.TW/TWD=X 日收盤)，含摘要卡（當前/均值/區間高低/百分位）+ 折溢價折線圖（左軸折溢價% + 均值線；右軸疊 2330 與加權指數 ^TWII，期初 rebase 到 100 同尺度，看溢價高低點 vs 股價/大盤相對位置）+ 近 20 日明細表。⚠ 時間差 (TSM 收盤晚 2330 約 14.5h，溢價為隔日開盤跳空前瞻指標) + 除權息假性折溢價 caveat。另有 `--alert` 模式：平日 08:00 cron 檢查，溢價 ≥25%(高檔) 或 ≤0%(翻折價) 才推 Telegram，平常安靜（2026-06-04 加）含「最新即時溢價」(2330 今日收盤 × TSM 最新美股收盤，跨時點即時參考) + 圖含折溢價斜率線 (滾動最小平方, pp/日) + 斜率轉折 ▲▼ 標記 + 隔日 2330 漲跌回測統計框 (5y: 轉負隔日72%跌/轉正67%漲 vs 48%基準) + 折線勾選顯示。→ `tw_adr_premium.py` (`slope_signals`) · `/adr-premium?period=1w|1mo|6mo|5y…` · cron `--alert --telegram`

# 台股籌碼 / 策略分析工具組

台股全市場籌碼監控 + 策略選股 + 回測的一站式工具組。網頁儀表板(深色終端機風、
手機可用):`http://localhost:5000` · 對外 `https://shudder-attention-musky.ngrok-free.dev`。

每個策略的**完整文件**(口徑/參數/資料源/回測結論/caveat)在 `docs/` 內,本檔只做索引。

## 📈 策略頁索引(依每日排程時間排序)

| 排程 | 策略 / 頁面 | 一句話 | 回測 | 文件 |
|---|---|---|---|---|
| 07:30 | 🌏 明天大盤預期 `/market-tomorrow` | 隔夜美股+台指期夜盤→隔日加權方向,推兩群 | ✅ 跳空87%/收收77% | [docs](docs/strategies/market-tomorrow.md) |
| 07:30 | 🔁 轉機接力(推播) | 兩層篩選:毛利改善+量能+ABCD 訊號 | ✅ 詳文件 | [docs](docs/tools/turnaround.md) |
| 07:35+21:45 | 🚀 FTD 反彈確認 `/ftd` | 歐尼爾修正期反彈確認日(加權/S&P/Nasdaq),新FTD推兩群 | ✅ 失敗率27.5%對上文獻;隔日弱/5-10日強 | [docs](docs/strategies/ftd.md) |
| 07:40 | 🌊 強勢股第二波(推播) | 強勢→急殺15-25%→反彈啟動 | ✅ 動能市限定 | [docs](docs/tools/second-wave.md) |
| 08:00 | 🇺🇸 ADR 折溢價 `/adr-premium` | TSM vs 2330 溢價序列 | — | [docs](docs/strategies/misc-signals.md) |
| 週一 08:10 | 📈 訊號成效追蹤(TG週報) | 各策略訊號後續表現追蹤 | — | [docs](docs/tools/signal-outcomes.md) |
| 盤中 */5 | 📐 期貨基差 `/futures-basis` | 除息調整後基差三訊號+外資留倉 caveat | — | [docs](docs/strategies/futures-basis.md) |
| 15:00 | 📐 林則行矩陣 `/lin-matrix` | 低量箱型→爆量突破,推兩群 | ⚠ 負超額,僅觀察 | [docs](docs/strategies/lin-matrix.md) |
| 15:30 | 🔥 個股期火熱 `/stock-futures` | 個股期量排行+基差/法人/四象限 17欄 | — | [docs](docs/strategies/stock-futures.md) |
| 16:00 | 🌙 借券雷達(推播) | 議借爆量×利率帶異常 | ✅ 高費率=負訊號 | [docs](docs/tools/lending-monitor.md) |
| 17:00 | 🔥 族群熱力(首頁) | 34 主題動能評分+點火+資金流 | ✅ 詳文件 | [docs](docs/tools/turnaround.md) |
| 17:00 | 📊 選擇權法人 `/option-flow` | 自營收put=恐慌事件標記,訊號日推 | ✅ 隔日無edge、5-10日反彈傾向 | [docs](docs/strategies/option-flow.md) |
| 18:00 | 🎯 主力雷達(推播+首頁榜) | 分點+融資連動 | ✅ 詳文件 | [docs](docs/tools/broker-radar.md) |
| 18:30 | 🎫 權證量能 `/warrant-signal` | 六類權證爆量×失衡 | ⚠ 無edge,觀察 | [docs](docs/strategies/warrant-signal.md) |
| 20:00 | 📊 一年高低榜 `/extremes` | 距一年高跌最深/距低漲最多 Top20,推兩群 | — | [docs](docs/strategies/extremes.md) |
| 20:40 | 🌐 外資成本線 `/foreign-cost` | 遞迴外資成本,110-140% 穩健區+140%+動能區 | ✅ 單調梯度:獲利越多越強 | [docs](docs/strategies/foreign-cost.md) |
| 20:50 | 🛡 抗跌領頭羊 `/utility-screen` | Minervini 修正期區間RS(距高點天數為窗)卡片牆 | ⚠ 未回測 | [docs](docs/strategies/utility-screen.md) |
| 21:00 | 🌀 VCP 波動收縮 `/vcp` | 遞減收縮+量縮+pivot,突破日推 | ⚠ 未回測 | [docs](docs/strategies/vcp.md) |
| 21:30 | 🌙 空頭撤退(推播) | 借券賣餘大減+🎯重空回補(股本%口徑) | ✅ 回補後5-10日唯一正超額 | [docs](docs/tools/lending-monitor.md) |
| 22:15 | 💥 融資斷頭潮 `/margin-scan` | 融資大減washout+賣壓/量%+維持率 | —(方法學驗證) | [docs](docs/strategies/margin-scan.md) |
| 每月1號 | 📅 月份季節性 `/seasonality` | 7指數月份勝率+台股漲停家數月統計 | —(統計) | [docs](docs/strategies/seasonality.md) |

**無排程(即時/CLI)**:💰 [資金流](docs/strategies/money-flow.md) ·
🧬 [籌碼價量 chip-price](docs/tools/chip-price.md) ·
💳 [融資維持率工具](docs/tools/margin-tools.md) ·
📉 [盤中模擬](docs/tools/turnaround.md) ·
🦖 [沉睡巨人](docs/tools/dormant-giants.md) ·
🔗 [美台聯動](docs/tools/us-correlation.md) ·
💼 [基本面工具(合約負債/存貨/股東)](docs/strategies/fundamentals.md) ·
🔔 [其他訊號](docs/strategies/misc-signals.md) ·
🔬 [借券大增/回補研究](docs/strategies/sbl-surge-study.md) ·
~~兩波對比~~([已下架](docs/strategies/chip-compare.md))

## 🧭 Minervini 三件套(工具鏈)

**🛡 Utility Screen**(修正期找抗跌股)→ **🌀 VCP**(型態成形/突破,🛡重合標記)→
**🚀 FTD**(大盤轉折定時機)。

## 🧱 共用基礎設施(詳 [docs/infra.md](docs/infra.md))

- **site_nav.py**:統一導航 + 深色終端機主題 + 表格自動排序/sticky/拖拉 +
  **全站 K 線彈窗**(點任何「代號 名稱」格 → 日K+MA5/20/60+VOL+MACD)。
  新頁面 checklist 見 memory `reference-site-nav`。
- **快取家族**(`concept_momentum/cache/`):year_prices(還原價)/ margin_hist /
  sbl_day / inst_day / vol_day / kline / shares_outstanding — 逐日全市場快取,
  各工具共用、每日增量。
- **推播**:Telegram 睏霸數錢(-5229750819)+ LINE 睏霸/田尾三人幫(額度 200/月);
  訊息連結一律 `site_nav.public_url()`(ngrok),不寫 localhost。
- **is_trading_day.py**:交易日守門(含臨時休市驗證)。cron 必帶 FINMIND_TOKEN。

## 📏 慣例(全站鐵律)

1. **紅漲綠跌**(台股慣例);數字帶 +/− 與 ▲▼(CVD 第二編碼)。
2. **有個股期的標的一律標 ★**(`tw_stock_futures.fut_stock_set()`)。
3. **網頁術語必須白話解釋**;未回測的策略必須紅字揭露。
4. **改動後全面檢查**:grep 同類 pattern、cron 時間 vs 頁面文案、非交易日文案。
5. **README 與策略文件隨每次改動同步更新**。

## 開發備忘

環境變數 / 檔案位置 / 回測共用工具(backtest_lib)/ 參數掃描(tw_param_sweep,
他人 WIP 勿動)/ 資料源文件 / 部署需求 / Backlog → 全在 [docs/infra.md](docs/infra.md)。

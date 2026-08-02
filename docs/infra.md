# 共用基礎設施與開發文件
> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 全站 UI/UX(site_nav 家族)

📈 **全站個股 K 線彈窗**(2026-08-01,用戶「對我很重要的功能」)— **全站任何列出「4碼代號+名稱」的表格格子點擊 → 彈出日 K 圖**:蠟燭圖(紅漲綠跌)+ **MA5/20/60**(黃/紫/青)、**VOL 副圖**(量柱依漲跌著色 + 5/20 量均線)、**MACD(12,26,9)副圖**(DIF 黃/MACD9 青/OSC 紅綠柱),深色終端機風,標題帶現價與漲跌幅,~160 交易日。組成:①`/api/kline/<code>`(app.py,FinMind `TaiwanStockPrice` 原始日K單股查詢,`cache/kline/{code}.json` 當日快取,含中文名)②`concept_momentum/static/kline.js`(自繪 canvas,零外部依賴;`/kline.js` route)③site_nav.nav_html 自動掛載(22 工具頁)+ 首頁兩模板 `</body>` 前掛載。**代號偵測**:regex「4 碼數字+空白+非數字(名稱)」→ 排除日期(2026-07-31)與價格(2425.00)誤觸;掃描 td 加 `.klx-c`(hover 青光提示),點擊委派排除 a/button/input/summary;Esc/背景點擊/✕ 關閉。實測:斷頭潮頁 481 個可點格,點 2429 銘旺科彈窗完整渲染。新頁面掛 site_nav 即自動獲得此功能。

🧪 **回測隨策略走(各策略區塊底部)**(2026-08-01,用戶更正:「不是所有回測同一頁,是把各策略的回測搬到各自的最下面區塊」)— 六個回測不再是獨立頁:**族群策略回測**→首頁「當日快照」分頁底、**第二波+轉機接力**→「盤前訊號」分頁底、**借券**→「借券動向」分頁底、**主力雷達**→「主力雷達歷史榜」分頁底、**盤中模擬**→`/intraday-sim` 頁尾;各為 `<details>` 摺疊區塊(🧪 標題點開)。實作:`dashboard()` route 改為讀 dashboard.html 後以 `_bt_fragment()`(呼叫原 view、抽 body、去 script/nav/h1)+`_inject_tab()` 注入;**注入片段 CSS 一律 `_scope_css()` 加 `#frag_id` 前綴隔離** —— 初版裸注入時回測頁的 `.pos{綠}` 全域蓋掉首頁 `.pos{紅}` 造成大盤寬度表紅綠反轉(截圖抓到),scope 後修復;CSS 變數(:root 被 scope 失效)以 `_BT_VARS` 全域補一次。舊回測網址 301 → 對應策略位置錨點(`/#bt-xxx`、`/intraday-sim#bt-intraday`);`/backtests` 總覽頁(存在約一小時)一併移除 301→首頁;首頁 g-backtest 群組移除。新回測上線:**寫進對應策略區塊底部,不開新頁**。同日 **`/chip-compare`(兩波比對)下架**(route 移除、首頁快查按鈕/tab、chip-price 第二排連結全清;模組檔保留)。

🖤 **深色終端機主題**（2026-07-31,承 36)— 全站改為「金融終端機」深色視覺。色票(`site_nav._SITE_CSS` CSS variables):底 `#0d1117`/卡 `#151b23`/線 `#223041`/主字 `#dfe6ee`/**accent 青 `#4cc2ff`**/**漲紅 `#ff6b6b` 跌綠 `#34c98e`**(dataviz 驗證器:對深底對比 ≥3:1 通過;紅綠對 deutan 色盲不可分為台股語意色必然,第二編碼=數字全帶 +/− 與 ▲▼)。工具頁(14)全由 site_nav 注入:sticky 玻璃導航列(backdrop blur、當前頁青色發光)、h1 漸層底線、表格 hover 青色微光、tabular-nums 等寬數字、深色表單/捲軸/選取色、狀態徽章(sigb/sigs/st-*)深色版、`section[style*=fff8e1]` 黃條提示轉深琥珀卡;**th sticky top 用 `--navh` CSS 變數**(JS 量測 nav 實高,nav 折行也不會蓋住表頭)。首頁另插同色票深色塊於 concept_charts.py(f-string,大括號 `{{}}`)+ dashboard.html 兩處(cron 重生成也保留):tab pill 深色+active 青色、lookup-bar 深卡(`!important` 蓋 inline 白底)、**Plotly 圖表保留白底圓角卡**(「深色框架、亮色圖卡」策略;plotly_dark 改版留待後續)。15 頁全 200 驗證。 全部由 `site_nav.nav_html()` 注入(掛統一 nav 的頁自動生效,零逐頁改表格 HTML):①**自動表格增強 `_ENHANCE_JS`**:每個 `<table>` 的 th 自動可點排序(數字/日期/字串智慧比對,`data-v` 優先;再點反向、▲▼ 指示;**th 已有自訂 onclick 的整表跳過**=不干擾 margin-scan/stock-futures 自帶多欄排序)+ 內容過寬的容器自動掛**滑鼠拖拉橫滑**(`.adrag`,自帶 `.dragx` 的跳過)+ **favicon 📈** 自動注入。②**全站統一樣式 `_SITE_CSS`**(注入於 body 內、晚於各頁 head style 故同權重勝出):頁寬統一 1100px、**表頭全站 sticky**、**深色模式**(`prefers-color-scheme: dark` 覆蓋 body/section/table/th/nav/.note/.small 等共同 class;熱力圖/徽章的 inline 色刻意保留)。③**首頁搜尋列合併**:原 5 組獨立「輸入框+按鈕」→ 單一輸入框 + 6 動作鈕(籌碼價量/融資維持率/合約負債/存貨/股東/兩波對比),Enter=籌碼價量(concept_charts.py 與 dashboard.html 同步;f-string 模板中 JS 大括號須 `{{ }}` 跳脫)。實測:extremes 點「現價」升降冪正常、margin-scan 自帶排序不受干擾(autoAttached=false)。

🧭 **全站統一導航 + UX P0 修復**（2026-07-31）— ①新增 `site_nav.py`:`nav_html(current)` 產生全站一致的導航列(15 個工具連結、當前頁粗體),14 個工具頁全部改用(root 8 個模組 + app.py 內 adr/futures-basis/chip-price/money-flow/intraday-sim + warrant renderer;新增頁面只要改 `NAV_LINKS` 一處)。舊況:每頁 nav 手寫子集、互相斷鏈、futures-basis/adr 只有部分連結。②`public_url(path)`:推播訊息的公開網址(ngrok 靜態域名 `shudder-attention-musky.ngrok-free.dev`,env `PUBLIC_BASE_URL` 可覆蓋)—— option-flow/ftd 推播原帶 localhost 手機點不開,已改。③主 dashboard 補 `<meta viewport>`(原缺→手機縮成桌面版)。④`/stock-futures` **回退最近交易日**:原本當日資料未公布(15:30 前)整頁錯誤,現自動回退(最多 5 日)+ 頁頂黃條標註「顯示最近交易日 X,今日約 15:30 後更新」(指定 `--date` 則不回退)。



## 資料源更新(2026-05-11 FinMind 遷移)


升級 FinMind sponsor 後遷移多個工具的資料源，提升穩定性 + 統一資料源：

- **借入交易** (lending_lookup + lending_monitor) → FinMind `TaiwanStockSecuritiesLending`，解決 TWSE rate-limit 問題
- **借券賣出餘額** → FinMind `TaiwanDailyShortSaleBalances`（TWSE + TPEx 統一）
- **日線價格** (second_wave + dormant_giants + concept_momentum + limitup_signal Yahoo 部分) → FinMind `TaiwanStockPrice`
- **還券明細** (lending_lookup) — **仍用 TWSE t13sa870**（FinMind 無此 dataset）；2026-07-18 起內建 rate-limit retry（3 次、間隔 25s — 之前被限流會靜默回空、與「真無還券」無法分辨，5347 敘事因此誤報缺資料）。⚠ 其 startDate/endDate 為**借入日**區間非還券日
- **分點 BSR** (broker_monitor + broker_lookup) — **仍用 TWSE/TPEx + Playwright**（FinMind sponsor 無 per-broker dataset）

新增共用模組 `finmind_client.py`（thin FinMind v4 wrapper），所有工具透過它存取 FinMind。

---


## 環境變數


| 變數 | 用途 | 來源 |
|------|------|------|
| `TG_BOT_TOKEN` | Telegram Bot 推送 | `~/.claude/channels/telegram/.env` |
| `FINMIND_TOKEN` | FinMind API | 個人 token |

---


## 檔案位置總覽(歷史文件,新快取以各策略文件為準)


```
~/project/tw_stock_tools/
├── tw_lending_monitor.py      # 借券議借 + 借券賣出減少監控（每日排程）
├── tw_lending_lookup.py       # 單檔借券查詢（CLI）
├── tw_margin_monitor.py       # 融資維持率全市場掃描（含 cohort 分布）
├── tw_margin_lookup.py        # 單檔融資維持率 + cohort 分析（CLI）
├── bsr_scraper.py             # TWSE BSR 爬蟲（ddddocr 解 CAPTCHA）
├── tpex_scraper.py            # TPEx 分點爬蟲（patchright + Xvfb 解 Turnstile）
├── tw_broker_monitor.py       # 分點+融資連動分析全市場掃描（每日排程）
├── tw_broker_lookup.py        # 單檔分點+融資連動分析（CLI，需 BSR 累積 ≥2 天）
├── tw_broker_history_lookup.py # 個股 N 天累積分點查詢（HiStock 爬蟲，CLI）
├── tw_us_correlation.py       # 台股 ↔ 美股 peer 相關性查詢（CLI，β 調整 / 全市場掃描）
├── tw_turnaround_screener.py  # Turnaround 篩選（毛利率↑+量能↑+借券↓，CLI）
├── tw_limitup_signal.py       # ABCD 接力型訊號分析（standalone 漲停掃描 / Layer 2 用）
├── tw_daily_screen.py         # 每日兩層篩選工作流（Layer 1 + Layer 2，19:00 cron）
├── tw_dormant_giants.py       # 沉睡巨人篩選器（曾 5x / 跌 ≥30% / 沉睡 ≥5y / 量縮整理）
├── dormant_cache/             # Yahoo 18y 還原股價快取（git ignore，cache 7 天）
├── tw_second_wave.py          # 強勢股第二波篩選器（強勢漲 → 急殺 → 反彈啟動）
├── second_wave_cache/         # Yahoo 9m 日線快取（git ignore，cache 1 天）
├── screener_cache/            # FinMind 季報 + 借券餘額快取（git ignore）
├── limitup_cache/             # 漲停訊號工具快取（市場/個股/SBL/HiStock，git ignore）
├── concept_momentum/          # 概念動能子模組（詳見內部 README.md）
├── margin_cache/              # FinMind 融資快取（git ignore）
│   └── finmind_{code}_{date}.json
├── bsr_cache/                 # BSR 分點 cache（git ignore）
│   └── {code}_{date}.json
├── bt_cache/                  # 回測價格面板 v2（git ignore，backtest_prices.py 產出）
│   └── backtest_prices_v2.json
├── lending_monitor.log        # 排程 log（git ignore）
├── broker_monitor.log         # 排程 log（git ignore）
├── README.md                  # 本文件
└── .gitignore
```

---


## 回測共用工具(backtest_lib)


所有回測頁底部有 📚 術語說明（CI/t/中位數/日期配對基準/非重疊/block bootstrap 等），方便直接對照解讀。

**`backtest_lib.py`** — 所有回測腳本 (強勢股第二波、主力雷達、概念動能等) 共用的統計與成本模型。

**成本模型 (cost_roundtrip_pct)**：買賣一趟成本 = 手續費 0.1425% × 2 × 折扣 + 證交稅 0.3% + 滑價。預設 6 折手續費、無滑價 → **0.471%**。支援調整折扣與單邊滑價（bp）。

**統計顯著性**：
- Percentile bootstrap 95% CI（均值）— 內建 5000 次重抽樣、seed 可設
- Moving-block bootstrap — 處理自相關時間序列（用於 rolling 窗口回測）
- t-stat — 超額報酬 t 統計量

**Episode 去重（dedup_cooldown）**：觸發訊號後 N 根 K 棒內不再進場，避免同檔股票連續交易。

**事件摘要（summarize_events）**：統一報告樣本數、絕對/超額報酬均值中位數、95% CI、t 統計、淨收益、勝率、成本；支援 edge sample（每事件 vs 同日隨機基準）的邊際收益分析。

---


## 參數敏感度掃描(tw_param_sweep,他人 WIP 勿動)


強勢股第二波 / 轉機接力兩策略的偵測參數，逐一 (one-at-a-time，其餘固定為現行預設) 掃描候選值，各自跑 `tw_second_wave_backtest.py` / `tw_turnaround_backtest.py` 的 `run()` 並切 **IS (2025-01-01~2026-03-31) / OOS (2026-04-01~)** 兩窗，比較 IS 有沒有進步、OOS 有沒有跟著撐住 —— 抓「只是 IS 過擬合」的參數組合。

**用法：**
```bash
python3 tw_param_sweep.py --strategy both               # 全掃兩策略（second_wave ~18 run、turnaround ~11 run，逐 run 5-15 分鐘）
python3 tw_param_sweep.py --strategy turnaround          # 只掃轉機接力
python3 tw_param_sweep.py --horizon 10 --json-out out.json
python3 tw_param_sweep.py --strategy turnaround --only gm_qoq 3   # 只跑預設組合 + 這一組（局部驗證/快速測試用）
nohup python3 tw_param_sweep.py --strategy second_wave > bt_cache/sweep_sw.log 2>&1 &   # 建議背景跑
```

**掃描 spec（寫在檔內 `SWEEP_SPEC`，中間值＝現行預設）：**

| 策略 | 參數 | 候選值 | 現行預設 |
|---|---|---|---|
| second_wave | rally_min_gain | 0.20 / 0.30 / 0.45 | 0.30 |
| second_wave | drop_min | 0.10 / 0.15 / 0.20 | 0.15 |
| second_wave | drop_max | 0.22 / 0.25 / 0.30 | 0.25 |
| second_wave | min_drop_days | 3 / 5 / 8 | 5 |
| second_wave | max_drop_days | 12 / 15 / 20 | 15 |
| second_wave | max_recovery_days | 7 / 10 / 15 | 10 |
| second_wave | recovery_min_gain | 0.03 / 0.05 / 0.08 | 0.05 |
| second_wave | recovery_vol_ratio | 0.5 / 0.7 / 1.0 | 0.7 |
| second_wave | max_today_vs_peak | 0.95 / 0.98 | 0.98 |
| turnaround | gm_pp | 1.0 / 1.5 / 2.5 | 1.5 |
| turnaround | gm_qoq | 1 / 2 / 3 | 2 |
| turnaround | vol_ratio | 1.15 / 1.3 / 1.5 | 1.3 |
| turnaround | sbl_decline | 0.90 / 0.95 / 1.00 | 0.95 |
| turnaround | ma_curv_ratio | 0.0 / 0.5 / 1.0 | 0.5 |

（second_wave 的 `peak_lookback` / `min_recovery_days`、turnaround 的 `ma_accel_days` 是結構性參數，固定不掃。預設組合兩策略各只共用跑 1 次 → 動態算出總 run 數：second_wave 8×2+1+1=18、turnaround 5×2+1=11，共 **29**。）

**快取（resumable）：** 每個 run 存 `bt_cache/sweep/{strategy}__{param}__{value}.json`（預設組合存 `{strategy}__default__.json`），只存該 run 的 `windows` 切窗結果。檔案已存在就跳過 → 可分次/多 session 續跑、中斷重跑不重算。

**彙總 JSON（`concept_momentum/cache/param_sweep.json`）：**
```
{generated, horizon, windows, strategies: {
  second_wave / turnaround: {
    default: {IS: {...}, OOS: {...}},
    params: {param: [{value, is_default, IS: {n, exc_mean, exc_ci, edge_mean, edge_ci}, OOS: {...}}]},
    proposals: [...], overfit_flags: [...]
}}}
```
缺快取的 run（尚未跑或只跑了子集）在彙總裡標 `"pending": true`，不算錯誤 —— 可以邊跑邊看目前彙總進度。

**提案規則（機械判定，寫死在程式裡，相對預設組合）：**
- `IS.edge_mean` 提升 **≥ 1.0pp** 且 `OOS.edge_mean ≥ 預設 OOS.edge_mean − 0.5pp` 且 `OOS.n ≥ 30` → 進 `proposals`
- 只有 IS 贏（≥1.0pp）但 OOS 不過關 → 進 `overfit_flags`（過擬合警訊）
- `edge_mean` 缺值（`None`，樣本不足時 `summarize_events` 不產生此欄）→ 該候選值不進兩份名單

**⚠ 這是提案分析工具，不是自動調參器** — 它只產生 `proposals` / `overfit_flags` 供人工檢視，**不會、也不應該自動改動任何 live 策略參數**（`tw_second_wave.py` 的 `FILTER_DEFAULTS` / `tw_turnaround_screener.py` 的 `TR_DEFAULTS` 都要人工評估後手動修改）。

---


## 資料源文件


### TWSE 公開 API
- `t13sa710`：SBL 借券交易（上市+上櫃）
  - `https://www.twse.com.tw/SBL/t13sa710?startDate=YYYYMMDD&endDate=YYYYMMDD&stockNo=CODE&response=json`
- `t13sa870`：SBL 還券明細
  - `https://www.twse.com.tw/SBL/t13sa870?startDate=YYYYMMDD&endDate=YYYYMMDD&stockNo=CODE&response=json`
- `TWT93U`：信用額度總量管制（含借券賣出餘額）
  - `https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=YYYYMMDD&response=json`
- `MI_MARGN` (OpenAPI 版本，不被反爬)：今日融資融券餘額
  - `https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN`

### TPEx 公開 API
- 上櫃借券賣出餘額：`https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=YYYY/MM/DD&response=json`
- 上櫃融資（OpenAPI）：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance`

### TWSE BSR 分點（需 CAPTCHA）
- 入口：`https://bsr.twse.com.tw/bshtm/bsMenu.aspx`
- 5 碼英數圖形 CAPTCHA，用 ddddocr 解
- 必須帶 `__VIEWSTATE`、`__VIEWSTATEGENERATOR`、`__EVENTVALIDATION` 三個 hidden 欄位
- POST 後從回應抓 `HyperLink_DownloadCSV` 連結，下載 CSV（cp950 編碼）
- 只有當日資料

### TPEx 分點（需 Cloudflare Turnstile）
- 入口：`https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html`
- Cloudflare Turnstile 自動解鎖：必須用 patchright + Xvfb（headed mode）
- 點擊 CSV 下載按鈕取得完整資料（cp950 編碼）

### FinMind
- 融資融券歷史（per-stock total）：`TaiwanStockMarginPurchaseShortSale`（免費版可用）
- 個股基本資料：`TaiwanStockInfo`（免費版可用）
- 借券交易 (per-stock total)：`TaiwanStockSecuritiesLending`（贊助版）
- 全市場一日借券賣出餘額：`TaiwanDailyShortSaleBalances`（贊助版）
- 單檔查詢需要 data_id，`start_date` 和 `end_date`
- 免費版 600 req/hr
- ❌ **沒有 per-(分點 × 融資/現股) 的 dataset**。v4/v3 完整 enum 掃過，連贊助 tier 也沒有此維度資料。實測 `TaiwanStockTradingDailyReport` 不存在 (2026-05-13)。

### Yahoo Finance
- 歷史價格：`https://query1.finance.yahoo.com/v8/finance/chart/{code}.TW?interval=1d&range=3mo`
- 上櫃用 `.TWO` 後綴
- 加權指數用 `^TWII`

### TWSE ISIN（中文名對照）
- 上市：`https://isin.twse.com.tw/isin/C_public.jsp?strMode=2`
- 上櫃：`https://isin.twse.com.tw/isin/C_public.jsp?strMode=4`
- HTML 頁面，**用 `cp950` 解碼**（不要用 `big5`，會丟失字如「碁」）

---


## 部署需求


### 系統套件
```bash
# 基本
sudo apt install xvfb libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
                 libatk-bridge2.0-0 libcups2 libxcomposite1 libxdamage1 \
                 libxfixes3 libxrandr2 libgbm1 libxkbcommon0 \
                 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0
```

### Python 套件
```bash
pip install requests beautifulsoup4 ddddocr patchright matplotlib plotly flask
python3 -m patchright install chromium
```

---


## WSL2 cron 漏跑補救(cron_catchup)

22. **WSL2 cron 漏跑補救** — WSL 被暫停時 cron 跳過不補；catch-up 腳本 @reboot + 平日每小時檢查當日輸出檔缺否，缺且過排程時間就補跑（idempotent, flock, token 從 crontab 抓）→ `cron_catchup.sh`。**長工防雙跑** (2026-07-17 加)：輸出檔在 job 結束才寫，主力雷達要跑 26-105 分鐘，正常 cron 執行中補跑會開第二個 instance（2026-07-13 主力雷達雙跑事件）→ `run_if_missing` 先 `pgrep -f` 同 script 是否執行中，是就跳過交給下一輪；tw_lending_monitor.py 供 lending/sbl 共用可能互相 false-positive 跳過，無害（hourly 下輪會補）


## 策略改進 Backlog


1. **盤中模擬 (intraday-sim) 的處置**：回測已證明無方向 skill（skill_vs_zero -2.4%，方向命中 51.6% vs 「永遠猜跌」57%）且信心帶過窄（41% vs 目標 50%）。選項：(a) `/intraday-sim` 頁面頂部加紅字告示「回測顯示無方向預測力，僅供情境想像」；(b) 加寬帶寬重新校準；(c) 下架。至少做 (a)。
2. **主力雷達訊號設計**：Pearson corr 算在 n=5 天上幾乎無過濾力（`tw_broker_lookup.py:212`）。bsr_cache 已累積 40+ 天 → 可改 `--days 10`。注意：改參數後 `broker_radar_history` 新舊事件不可混合回測，需重新累積 1-2 個月再評估。改前先用現行回測基準線存檔。
3. **參數敏感度掃描**：對第二波 7 條件、TR 6 參數做 grid 掃描 + walk-forward（2025 調參 / 2026 驗證）。必須在 Task 3/10 之後做（有了可信的衡量才有調參的意義）。
4. **倖存者偏差**：universe 改用含下市股的清單（FinMind `TaiwanStockInfo` 含 `date` 欄位可判斷；或 TWSE 下市公司名單），回測面板補抓已下市股票價格。
5. **美台聯動多重比較**：`--scan` 對 ~190 檔挑最高相關 = winner's curse。輸出加 split-half 驗證欄（前半窗 vs 後半窗 corr 同號才標「穩定」）。
6. **turnaround screener 資料源**：Yahoo → FinMind（其他工具 2026-05-11 已遷移，`tw_turnaround_screener.py:40` 還在用 Yahoo，rate-limit 靜默跳過會讓 universe 每天不同）。同時加「抓取失敗計數」到輸出——區分「無候選」與「資料斷線」。
7. **組合層模擬**：事件研究之上加簡單組合模擬（同時最多 K 檔、等權、資金重複使用規則），回答「這些策略疊起來的資金曲線長怎樣」。
8. **沉睡巨人 / 美台聯動 回測**：沉睡巨人持有期長（月~年），需要不同的評估框架（6m/12m horizon + 觸發稀少）；美台聯動是配對訊號非選股訊號。各開獨立 plan。
9. **dormant_giants 還原價來源**：Yahoo adjclose → FinMind `TaiwanStockPriceAdj`（sponsor 已可用，README 註記過時）。

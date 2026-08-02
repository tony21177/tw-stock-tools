# 台股借券 / 融資 / 籌碼 / 概念動能分析工具組

## 🎯 八大策略總覽

| 策略名 | 工具 | 排程 | 用途 |
|--------|------|------|------|
| 🌅 **轉機接力** (TR) | `tw_daily_screen.py` | 盤前 07:30 | Layer 1 turnaround + Layer 2 ABCD 接力 兩層篩選 |
| 🌅 **強勢股第二波** | `tw_second_wave.py` | 盤前 07:40 | 強勢漲 → 急殺 15-25% → 反彈啟動 |
| 🌙 **借券雷達** | `tw_lending_monitor.py --mode lending` | 盤後 16:00 | 議借量突增 + 利率異常 |
| 🌙 **族群熱力** | `concept_momentum/run_daily.py` | 盤後 17:00 | 概念動能評分 + Rerating + 業務轉型 |
| 🌙 **主力雷達** | `tw_broker_monitor.py` | 盤後 18:00 | 分點買賣超 + 融資連動 = 主力建倉 |
| 🌙 **空頭撤退** | `tw_lending_monitor.py --mode sbl` | 盤後 21:30 | 借券賣餘大幅減少 = 空方回補 |
| 🔍 **沉睡巨人** | `tw_dormant_giants.py` | CLI | 曾 5x、跌 ≥30%、沉睡 ≥5y、量縮整理 |
| 🔍 **美台聯動** | `tw_us_correlation.py` | CLI | β 調整 TW vs US peer 相關性 |

---

## 📦 全部工具清單 (十九項)

1. **借券雷達** — 借券議借異常監控（盤後 16:00 排程） → `tw_lending_monitor.py --mode lending`
2. **空頭撤退** — 借券賣出餘額大幅減少監控（盤後 21:30 排程） → `tw_lending_monitor.py --mode sbl`
3. 單檔借券狀況查詢（CLI）→ `tw_lending_lookup.py`
4. 融資維持率預警全市場掃描（含批次分布）→ `tw_margin_monitor.py`
5. 單檔融資維持率估算 + 批次 cohort 分析（CLI）→ `tw_margin_lookup.py`
6. **主力雷達** — 分點+融資連動分析（盤後 18:00 排程） → `tw_broker_monitor.py` / `tw_broker_lookup.py`
7. **族群熱力** — 概念動能監控 + Rerating + 業務轉型（盤後 17:00 排程 PNG + 網頁儀表板）→ `concept_momentum/`
8. **美台聯動** — 台股 ↔ 美股 peer β 調整相關性（CLI）→ `tw_us_correlation.py`
9. Turnaround 篩選器（毛利率改善 + 量能放大 + 借券回補，轉機接力 Layer 1）→ `tw_turnaround_screener.py`
10. ABCD 接力型訊號分析（轉機接力 Layer 2 / 或 standalone CLI）→ `tw_limitup_signal.py`
11. **轉機接力** — 每日兩層篩選工作流（盤前 07:30 cron）→ `tw_daily_screen.py`
12. **沉睡巨人** — 曾 5 倍、跌 ≥30%、沉睡 ≥5y、量縮整理（CLI）→ `tw_dormant_giants.py`
13. **強勢股第二波** — 強勢漲 → 急殺 → 反彈啟動（盤前 07:40 cron）→ `tw_second_wave.py`。2026-07-19 加 `--line-to <U/C開頭ID,可逗號多個>`：報告同步推 LINE（共用 `line_push.py` 模組，憑證 env `LINE_CHANNEL_ID`+`LINE_CHANNEL_SECRET` 自動換發 token）；cron + cron_catchup 均已掛 田尾三人幫 群組
14. **日內籌碼×價格** — 當日 BSR broker × price 二維分析（CLI / Skill）→ `tw_chip_price.py`
15. **合約負債歷史** — 單檔近 N 年每季合約負債 + QoQ/YoY/CAGR（CLI + 網頁；FinMind 缺資料時 fallback MOPS 季報 PDF 附註，2026-05-20 加 fallback）→ `tw_contract_liabilities.py` · `mops_pdf.py` · `/contract-liabilities?pdf=1`
16. **存貨歷史 + 衍生指標** — 單檔近 N 年每季存貨 + 週轉率/DSI/存貨營收比 + 圖表（CLI + 網頁，2026-05-15 加）→ `tw_inventory.py` · `/inventory`
17. **存貨 5 項拆分** — 從 MOPS 財報 PDF 解析原料/在製品/半成品/製成品/副產品/物料拆分，疊圖顯示（2026-05-17 加；2026-05-22 加平行下載 + ProcessPool 解析 20 季 80s→30s、網頁拆分回看年數下拉、解讀邏輯 YoY 為主 + QoQ 連 2 季同向加倍強化 ⚡ + 營收交叉警訊「存貨雙升 vs 營收沒跟上 → 庫存壓力劇增 🔴」、拆分表多 4 欄存貨總額 / 季營收 / 存貨銷售比 / DSI 天 色碼，存銷比 + DSI 互相驗證跨季節更穩定）→ `mops_pdf.py` · `/inventory?breakdown=1`
18. **族群點火警示** — 偵測族群評分「休眠 → 轉強」事件（昨 <3 → 今 ≥10, Δ ≥8），自動標真假機率 + 5 日後續追蹤倍率（concept_momentum 17:00 cron + dashboard 🔥 族群點火 tab，2026-05-18 加）→ `concept_momentum/run_daily.py` · `/`
19. **分點 N 日時段 pattern** — 給定 (股號, 分點)，自動算過去 N 日該分點在早/中/尾盤的買賣分布 + 配對 OHLC 走勢 + 6 種行為標籤（尾盤低接 / 早盤追擊 / etc）+ 可展開的專有名詞詳細解讀（2026-05-20 加）→ `broker_timing_pattern()` in `tw_chip_price.py` · `/chip-price?code=X&broker=Y`
    - **📱 每日敘事 LINE 推播** (2026-07-18 加) — 22:00 平日 cron（`is_trading_day` 守門）跑 `concept_momentum/chip_narrative_push.py`：讀 `chip_narrative_watchlist.json`（動態清單，改 JSON 即生效，預設 2313/3491/5347、mode=full），逐檔抓當日 BSR → 產生完整版敘事（同日已有快取直接重用、不重複扣 Claude 用量）→ 推 **LINE Messaging API**（LINE Notify 已於 2025-03 停服）。**資料完整性守門**（2026-07-20 加）：重用快取前檢查 `generated_at` — 若快取是**當日 21:30（融資~21:00/借券 21:30 公布）之前**產生（例：使用者下午在網頁按了完整版），該敘事融資/借券當日值不全（會寫「以前一日為準」），推播端**強制重跑**用齊全資料覆寫，避免 22:00 推出盤中舊資料版。憑證：cron env `LINE_CHANNEL_ID` + `LINE_CHANNEL_SECRET`，程式每次執行自動換發 access token（30 天效期、免管理；也可直接給 `LINE_CHANNEL_TOKEN`）。收件者：config `line_recipients`（U開頭=個人、C開頭=群組，目前推兩個群組；env `LINE_USER_ID` 為 fallback）。群組 ID 需靠臨時 webhook（cloudflared quick tunnel + bot join event）抓取，bot basicId=@cyb6894h。⚠ 免費額度 200 則/月、每收件者each計一則（群組算 1 不論人數），目前 2群×3檔×22日≈132。訊息自動去 markdown、依 5000 字元上限切塊（單次 push ≤5 則）。**LINE 憑證未設定時退化成只產生敘事快取**（網頁 /chip-price 可看），不浪費。逐檔 sequential 避免多個 claude 進程並行。測試：`--dry-run [--codes 2313]`。選 22:00 是因為借券賣出餘額 21:30 公布，三線資料全齊
    - **⚡ 隔日沖分點標記** (2026-07-23 加) — `daytrade_brokers.py` 維護隔日沖/短線大戶分點註冊表 `cache/daytrade_brokers.json`，三來源：①靜態種子(公認名單:凱基松山/城中/信義、美林、摩根大通、國票敦北…web 交叉驗證) ②**多來源網路交叉比對**(headless `claude -p` 搜股感/玩股網/CMoney/豐雲學堂等，≥2 來源=confirmed、單來源=candidate；不靠單一來源) ③**資料驅動偵測**(掃近 50 日 bsr_cache plain 檔，算每分點「大買後隔日倒的比例」= dumps/big_buys，≥50%=confirmed/≥30%=candidate，高分自動加、標 data 來源+分數)。分點行為序列每筆多 `⚡隔日沖`(confirmed)/`⚡隔日沖?`(candidate) 標籤(**額外標籤、不改外資/內資/散戶分類**)，敘事 prompt 明文「⚡隔日沖分點的買盤≠內資機構認同」。週日 09:30 cron `--weekly` 更新兩來源。緣起：永豐金匯立(9A81)是本土永豐證券歸「內資」正確，但「內資」不等於機構、公認隔日沖是凱基松山/美林/摩通等(永豐匯立經 web+我方資料雙重確認**不在**名單)。CLI `--data`/`--web`/`--list`
    - **🤖 AI 行為敘事按鈕** (2026-07-17 加，同日加完整版) — `/chip-price` 報告頁一鍵觸發本機 headless Claude CLI 產生敘事分析，完成後自動顯示在頁面。**兩檔模式**：(a) **完整版（主按鈕，預設）** — `claude -p --dangerously-skip-permissions` agentic 執行，讀 chip/chip-price 兩個 SKILL.md 紀律後實際跑三線整合（分點多日序列 + 借券/SBL + 融資 + 30 天內除權息查核）再交叉寫敘事（外資動向 → 內資逐分點 → 散戶 → 借券/融資/除權息交叉檢核 → 結論 + 明日觀察重點），約 5-10 分鐘，timeout 25 分；prompt 明文禁止推 Telegram/寫檔/重抓 BSR 網站（只用既有 cache）。(b) **快速版** — 純文字單回合，只餵「近 10 日分點連續買賣序列」+ 內嵌判讀紀律，約 1-2 分鐘。背景 thread + 檔案狀態機（`cache/chip_narrative/{code}_{date}[_full].json` + `.status.json`，跨 process 安全、stale 自動可重試：quick 7 分 / full 30 分）；同 (code, date, mode) 有快取直接顯示（**每次產生 = 一次 Claude 用量，完整版較高**），顯示優先完整版，可各自「重新產生」。CLI 測試：`python3 chip_narrative.py 2313 20260716 [--full] [--prompt-only]`。API：`POST/GET /api/chip-narrative?code=&date=&mode=full|quick`
20. **前十大股東 + 集保大戶分布** — 輸入股號查 (a) MOPS 年報前十大股東（姓名 + 持有股數 + 持股比例 + 停止過戶日 + **關係人備註**；候選頁逐一解析容錯各家 layout、F04「主要股東名單」乾淨排名表為主、F17 前十大股東相互間關係表 fallback、按持股比率排序、<5 筆視為失敗、JSON+負快取）。關係人欄列出年報揭露的前十大股東相互間配偶/二親等/法人關係（如 2313 吳家三代、2408 台塑集團交叉持股、法人股東代表人/董事長）；可載入 **N 年（3/5/8/10）變化矩陣**（股東 × 年度持股% + ▲▼ 趨勢 + ★新進/已退榜，跨年用 F17 標準表 + 名稱正規化合併同一實體）；(b) 集保 TDCC 每週股權分散表，4 群組摘要（散戶/中實戶/大戶/千張大戶）+ 籌碼集中度趨勢線 + 級距長條圖 + 各群組週變化表（%/張數/人數）（2026-05-28 加）→ `fetch_major_shareholders()` in `mops_pdf.py` · `fetch_holding_distribution()` in `finmind_client.py` · `/shareholders?code=X`

21. **TSM ADR vs 2330 折溢價** — TSM (台積電 ADR) 與台股 2330 的折溢價歷史，可選區間 1 週 / 2 週 / 1 / 3 / 6 個月 / 1-10 年（預設 6 個月）。換股比例 1:5，理論價 = TSM(USD)×USD/TWD÷5，折溢價 = (理論價/2330實際價−1)。資料 Yahoo (TSM/2330.TW/TWD=X 日收盤)，含摘要卡（當前/均值/區間高低/百分位）+ 折溢價折線圖（左軸折溢價% + 均值線；右軸疊 2330 與加權指數 ^TWII，期初 rebase 到 100 同尺度，看溢價高低點 vs 股價/大盤相對位置）+ 近 20 日明細表。⚠ 時間差 (TSM 收盤晚 2330 約 14.5h，溢價為隔日開盤跳空前瞻指標) + 除權息假性折溢價 caveat。另有 `--alert` 模式：平日 08:00 cron 檢查，溢價 ≥25%(高檔) 或 ≤0%(翻折價) 才推 Telegram，平常安靜（2026-06-04 加）含「最新即時溢價」(2330 今日收盤 × TSM 最新美股收盤，跨時點即時參考) + 圖含折溢價斜率線 (滾動最小平方, pp/日) + 斜率轉折 ▲▼ 標記 + 隔日 2330 漲跌回測統計框 (5y: 轉負隔日72%跌/轉正67%漲 vs 48%基準) + 折線勾選顯示。→ `tw_adr_premium.py` (`slope_signals`) · `/adr-premium?period=1w|1mo|6mo|5y…` · cron `--alert --telegram`
22. **WSL2 cron 漏跑補救** — WSL 被暫停時 cron 跳過不補；catch-up 腳本 @reboot + 平日每小時檢查當日輸出檔缺否，缺且過排程時間就補跑（idempotent, flock, token 從 crontab 抓）→ `cron_catchup.sh`。**長工防雙跑** (2026-07-17 加)：輸出檔在 job 結束才寫，主力雷達要跑 26-105 分鐘，正常 cron 執行中補跑會開第二個 instance（2026-07-13 主力雷達雙跑事件）→ `run_if_missing` 先 `pgrep -f` 同 script 是否執行中，是就跳過交給下一輪；tw_lending_monitor.py 供 lending/sbl 共用可能互相 false-positive 跳過，無害（hourly 下輪會補）
    - **交易日守門 `is_trading_day.py`**：FinMind `TaiwanStockTradingDate` 日曆 + 本地快取；cal 拿不到時 fallback 週一~五。**臨時休市驗證** (2026-07-17 加)：FinMind 預排日曆**不含臨時停市**（2026-07-10 颱風假實際休市但日曆列交易日 → 全部盤後 cron 誤跑、TWSE BSR 回傳前日資料錯標成當日，219 個 bsr_cache 檔 + 7 個策略歷史檔污染）→ 日曆通過後，若查「過去日期」或「今天且已過 15:00」，加查 FinMind 2330 該日有無實際成交列，沒有就 exit 1；FinMind 異常時 fail-open 照日曆（寧可多跑不漏跑）。盤前 cron（07:30/08:50）當日資料未出、不做此驗證

23. **期現貨基差 / 外資期貨留倉監控** — 依「外資留倉沒有多空意義」一文：外資期貨留倉淨額 98% 是投行期現貨套利對沖腳、無方向意義，本工具顯示但標明 caveat；真正監控 (a) 基差 TX日盤 vs 加權現貨 vs 0.38% 套利成本帶 —— **⚠ 2026-07-22 修：加權指數是價格指數(除息當天蒸發點數)，除權息旺季(6-9月)會出現數百點「結構性逆價差」純屬待除息、非看空。新增「除息調整後基差 = 原始基差 + 結算前剩餘除息點數 D」，三訊號逆價差腳/basis_extreme/directional_warn 全改用調整後基差判斷。D 精算 = Σ 指數×(該股市值/全市場)×(每股股利/股價)，資料 `index_dividend_points.py`：全市場市值 `TaiwanStockMarketValue`(權重) + 逐檔 `TaiwanStockDividend`(除息日/現金股利，只查前 50 大權值股，指數集中頭部覆蓋~75-85%)；網頁/告警標覆蓋率%。結算日 = 近月合約月第三個週三** (b) 三訊號同步「跌+逆價差(調整後)+台幣貶=外資大賣超」(c) 基差-留倉套利一致性 (正價差+大空單=純套利印證；富台期/摩台期已無流動性，文章的大台富台交叉檢查不適用) (d) 月底轉倉 (f) **外資/法人 近月 vs 遠月台指部位** — FinMind 法人部位是全契約加總無法分月，改抓 TAIFEX 大額交易人未沖銷部位表（`fetch_tx_large_trader()`，解析臺股期貨「特定法人前十大」近月月契約/週契約/所有契約，遠月=全−近−週；特定法人＝外資+投信+自營大戶 proxy，非純外資）+ `TaiwanFuturesDaily` 逐月 OI（`fetch_tx_oi_by_month()`，市場層級看轉倉）；網頁 🧭 section 顯示特定法人近月/遠月/全契約淨部位 + 市場逐月 OI (e) 富台(SGX TWN)近月未平倉口數 — **TradingView scanner 端點自動抓** `SGX:TWN1!`（`fetch_twn_oi_live()`，純 HTTP JSON、無 CAPTCHA/Cloudflare；SGX 官網本身 Akamai 擋自動化故改走 TradingView），每次更新自動記錄建立歷史，網頁顯示最新值+Δ。`--remind-twn-oi` 改為自動抓取（抓到就記錄，僅在抓取失敗時推 Telegram 提醒手動補 `--log-twn-oi`）。網頁基差走勢圖+TX/XIF留倉圖+訊號狀態表+富台 OI，17:30 cron 告警 (只對有意義訊號，不對留倉淨額)→ `tw_futures_basis.py` · `/futures-basis` · cron `--alert --telegram` (17:30) + `--remind-twn-oi --telegram` (17:35, 自動抓 OI) · 手動補登 `--log-twn-oi <口數> [--date YYYYMMDD]`

43. 🌀 **VCP 波動收縮型態掃描**(`tw_vcp_screen.py` · `/vcp`,2026-08-02)— Minervini 核心買點型態(調研:TradingView/TrendSpider/Deepvue scanner 共識口徑)。**邏輯**:Stage 2 上升趨勢中的基底,回檔一次比一次淺(18%→12%→6%)+ 量能枯竭 = 供給被吸收,貼 pivot(基底右側高點)帶量突破 = 主升段買點。**偵測**:前置趨勢模板(價>MA50>MA150>MA200 且 MA200 走揚 + 距一年高<25% + 距一年低>+30% + 年RS≥70)→ VCP 本體(近130日):zigzag 5% 抓 swing → 回檔深度 2~6 段逐段遞減(≤前段×0.85)、首段≤30%、低點墊高、近10日振幅≤8%、量縮 vol5<vol50×0.65 → 「**形成中**」=距 pivot≤6% 且量乾涸;「**今日突破**」=收盤>昨日前 pivot 且 當日量≥1.5×50日均量 → **盤後推 Telegram**(vcp_pushed.json 去重)。呈現=卡片牆(mini K 線 + RS/收縮序列/乾涸值/量倍徽章;**🛡=同在抗跌領頭羊名單** = 修正期抗跌+VCP 最強組合;點卡開大圖)。首掃(大盤剛崩 −9.7%):母體 2,406 → 僅 1 檔形成中(環泰 9.9→6.5→5.1%、乾涸 0.43)——崩盤週基底盡毀,型態稀缺屬正常,盤穩後名單自然增。與 Utility Screen(找股)/FTD(定時機)構成 Minervini 完整流程。**每交易日 21:00 cron**。⚠ 未回測(林則行箱型台股回測為負的前車之鑑已在頁面揭露;VCP 多趨勢前提+遞減收縮+量縮,待驗)。CLI `--build`/`--telegram`/`--html`。

42. 🛡 **Utility Screen 抗跌領頭羊**(`tw_utility_screen.py` · `/utility-screen`,2026-08-02,依用戶提供 Minervini 文章)— **大盤修正期找下一波領頭羊**:修正期多數股跟跌,未來超級強勢股通常在修正期就異常抗跌(高 RS、貼高點、量縮不跌)。**啟動機制**:加權距「200 日內最高收盤」>20 個交易日 → 啟動,以**距高點天數 N 為視窗重算區間 RS**(N 逐日+1;首日 2026-08-02 啟動時 N=28,高點 47,742 @ 06-22、修正 −9.7%);大盤創高或 N>200 → 退回標準年 RS(N=250)。**區間 RS**=IBD 加權式(視窗切四段、最近段雙倍權重 2:1:1:1)→ 全市場百分位 1~99。**濾網**(文章口徑,不看一年低點):區間RS>85 + 股價>MA200 + MA50>MA200 + 日均成交額>1億(近20日 vol×收盤估)+ 距自身200日高<25%。首掃:母體 2,338 → **47 檔**(兆豐金★/華南金★/合庫金★/上海商銀★ 貼高點、漢翔★ +25%、仁新 +71%——修正期防禦+主題強勢的教科書組合)。**呈現=卡片牆**(依用戶提供的原作者截圖):頂部統計列(符合檔數/距高點日數/最高 RS/平均 RS)+ 每檔一張 **mini K 線卡**(近 120 根蠟燭紅漲綠跌 + MA20 黃/MA60 青 + 底部量柱,canvas 自繪、資料走 /api/kline 且 build 時 `_warm_kline` 預熱快取)+ RS 藍徽章/距高點橙徽章/成交額;**點卡片開大圖 K 線彈窗**(kline.js 加 `[data-kx]` 委派);完整表格收進摺疊「表格檢視」。**用法**:觀察清單非進場訊號——修正期掛名單看誰形成 VCP/量縮不跌,等 **FTD(/ftd)大盤轉折**時名單裡最先突破買點者=風報比最佳佈局(頁面已寫)。資料全走現有快取(year_prices/vol_day/TAIEX)。**每交易日 20:50 cron** 重建 JSON(extremes 20:00 先建價格快取),不推播。⚠ 未回測。CLI `--build`/`--html`。

41. 📈 **全站個股 K 線彈窗**(2026-08-01,用戶「對我很重要的功能」)— **全站任何列出「4碼代號+名稱」的表格格子點擊 → 彈出日 K 圖**:蠟燭圖(紅漲綠跌)+ **MA5/20/60**(黃/紫/青)、**VOL 副圖**(量柱依漲跌著色 + 5/20 量均線)、**MACD(12,26,9)副圖**(DIF 黃/MACD9 青/OSC 紅綠柱),深色終端機風,標題帶現價與漲跌幅,~160 交易日。組成:①`/api/kline/<code>`(app.py,FinMind `TaiwanStockPrice` 原始日K單股查詢,`cache/kline/{code}.json` 當日快取,含中文名)②`concept_momentum/static/kline.js`(自繪 canvas,零外部依賴;`/kline.js` route)③site_nav.nav_html 自動掛載(22 工具頁)+ 首頁兩模板 `</body>` 前掛載。**代號偵測**:regex「4 碼數字+空白+非數字(名稱)」→ 排除日期(2026-07-31)與價格(2425.00)誤觸;掃描 td 加 `.klx-c`(hover 青光提示),點擊委派排除 a/button/input/summary;Esc/背景點擊/✕ 關閉。實測:斷頭潮頁 481 個可點格,點 2429 銘旺科彈窗完整渲染。新頁面掛 site_nav 即自動獲得此功能。

40. 🧪 **回測隨策略走(各策略區塊底部)**(2026-08-01,用戶更正:「不是所有回測同一頁,是把各策略的回測搬到各自的最下面區塊」)— 六個回測不再是獨立頁:**族群策略回測**→首頁「當日快照」分頁底、**第二波+轉機接力**→「盤前訊號」分頁底、**借券**→「借券動向」分頁底、**主力雷達**→「主力雷達歷史榜」分頁底、**盤中模擬**→`/intraday-sim` 頁尾;各為 `<details>` 摺疊區塊(🧪 標題點開)。實作:`dashboard()` route 改為讀 dashboard.html 後以 `_bt_fragment()`(呼叫原 view、抽 body、去 script/nav/h1)+`_inject_tab()` 注入;**注入片段 CSS 一律 `_scope_css()` 加 `#frag_id` 前綴隔離** —— 初版裸注入時回測頁的 `.pos{綠}` 全域蓋掉首頁 `.pos{紅}` 造成大盤寬度表紅綠反轉(截圖抓到),scope 後修復;CSS 變數(:root 被 scope 失效)以 `_BT_VARS` 全域補一次。舊回測網址 301 → 對應策略位置錨點(`/#bt-xxx`、`/intraday-sim#bt-intraday`);`/backtests` 總覽頁(存在約一小時)一併移除 301→首頁;首頁 g-backtest 群組移除。新回測上線:**寫進對應策略區塊底部,不開新頁**。同日 **`/chip-compare`(兩波比對)下架**(route 移除、首頁快查按鈕/tab、chip-price 第二排連結全清;模組檔保留)。

39. 🌐 **外資成本線 110-140% 篩選**(`tw_foreign_cost.py` · `/foreign-cost`,2026-08-01)— 估**每檔外資成本**(比照融資遞迴成本線 XQ 口徑:今日成本=(昨成本×(持股−淨買)+還原收盤×淨買)÷持股;賣出以均價移除),篩**現價/外資成本 ∈ [110%,140%]** = 外資帳面獲利 10~40%(高於成本=有支撐外資未被套;<140%=未到獲利了結過熱區)。持股序列=今日官方外資持股(`TaiwanStockShareholding.ForeignInvestmentShares`)以每日買賣超往回反推(H_{t-1}=H_t−淨買_t,反推出負持股=資料不一致剔除);外資=Foreign_Investor+Foreign_Dealer_Self(FinMind `TaiwanStockInstitutionalInvestorsBuySell` 逐日全市場,快取 `cache/inst_day/` 已補 250 天)。**收斂度**=一年累積買進÷現持股:<0.3 不列入(萬年持股如台積電一年資料算不出真實成本,種子依賴重)。門檻:外資持股≥5% 發行股數、現價≥10元。**已交叉驗證**:遞迴成本 vs 獨立「買進量加權 VWAP」——矽力 +2.7%/瑞昱 −3.1%/樺漢 −5.0% 吻合;健鼎 −18% 為遞迴法正確語意(大賣後舊高成本批被均價移除,剩餘部位成本偏後期低接)。首掃 2026-07-31:母體 856 檔、區間內 125 檔(矽力123%/力旺111%/健鼎122%/瑞昱123%…)。欄:現價/成本/比/持股%/持股張/近20日淨買(紅買綠賣,同區間內「還在買vs調節中」意義不同)/收斂度。**每交易日 20:40 cron** 重建 JSON(法人+持股盤後公布;extremes 20:00 先建好當日價格快取),不推播。**已回測**(`tw_foreign_cost_backtest.py`,每5日取樣、point-in-time 成本、過濾同 live,18 取樣日):**單調梯度 —— 外資獲利越多之後越強**。<100(外資被套)H60 超額 **−14.7% 全表最弱**;100-110 −6.6%;**★110-140 超額轉正 +3.6%**(絕對勝率 69.4%/+28.7%,在平均個股超額 −12.6% 的年份)=策略有效;但 **140-180 +13.2%、>180 +14.2% 表現更好** ——「外資大賺會調節」在本樣本不成立,外資獲利=動能延續;**下限 110(過濾被套弱股)才是 edge 主要來源,上限 140 反而切掉最強一群**。⚠ 一年動能市 regime、取樣重疊、分布右偏、梯度與價格動能高度相關。結論嵌頁面(讀 `foreign_cost_backtest.json`)。CLI `--backfill`/`--build`/`--html`。

38. 🔬 **借券賣出大增/回補 事件研究**(`tw_sbl_surge_study.py`,2026-08-01)— 回答「借券賣出大增後股價怎麼走?大量後陸續回補又怎麼走?」。全市場 4 位數普通股、近一年(2025-07~2026-07,250 交易日、1937 檔),還原收盤計酬、超額=減同期加權。**門檻用「發行股數 %」**(用戶指正:借券賣出+融券合計法定上限=發行股數 10%,股本%才跨大小型股可比;發行股數=**官方 `TaiwanStockShareholding.NumberOfSharesIssued`**(外資持股表,全市場單日,`load_shares` 週快取;初版用市值÷收盤反推,用戶指正後改官方欄位,兩者結果幾乎相同);sanity:全市場餘額/股本%最大值 P50=1.5/P90=6.1/max=12.8%(個別 >10% 為年中減資:歷史餘額÷現在股數))。事件:**A 大增**=10日增量≥發行股數 0.5%(2255 次);**B 回補**=60日峰值≥股本 2%、首次跌破峰值 70%(1160 次);冷卻 40 日。**結論(兩種門檻口徑一致=穩健)**:①大增前 20 日平均 +5.5% → 空單多建在強勢股。②**「被大量借券空=會跌」不成立**:短期(1-2週)中性偏弱(H5 超額 −0.59% vs 對照 −0.97%),**H60 絕對 +17.7%/勝率 58.7% 遠勝對照 +7.7%/47.3%**、超額 −6.8% vs −12.6%(+5.8pp)——動能延續+軋空燃料,分布右偏(中位 +4.1%)。③**回補後 5-10 日=全表唯一超額轉正視窗**(H5 +0.25%/H10 +0.15% vs 對照 −0.97%/−1.98%,勝率 53.7%),回補買盤+風險解除;**H60 絕對 +19.1%/勝率 61.5%、超額差 +7.4pp = 全表最大**。④⚠ regime:本年平均個股超額 −12.6%/60日(權值撐盤),超額須 vs 對照讀;樣本一年含兩次崩盤;回補動機不唯一(召回/自主)。資料:TaiwanDailyShortSaleBalances 逐日全市場(cache/sbl_day/ 已補 250 天)+ year_prices。結果 `cache/sbl_surge_study.json`。CLI `--backfill`/`--json-out`。

37. 🖤 **深色終端機主題**（2026-07-31,承 36)— 全站改為「金融終端機」深色視覺。色票(`site_nav._SITE_CSS` CSS variables):底 `#0d1117`/卡 `#151b23`/線 `#223041`/主字 `#dfe6ee`/**accent 青 `#4cc2ff`**/**漲紅 `#ff6b6b` 跌綠 `#34c98e`**(dataviz 驗證器:對深底對比 ≥3:1 通過;紅綠對 deutan 色盲不可分為台股語意色必然,第二編碼=數字全帶 +/− 與 ▲▼)。工具頁(14)全由 site_nav 注入:sticky 玻璃導航列(backdrop blur、當前頁青色發光)、h1 漸層底線、表格 hover 青色微光、tabular-nums 等寬數字、深色表單/捲軸/選取色、狀態徽章(sigb/sigs/st-*)深色版、`section[style*=fff8e1]` 黃條提示轉深琥珀卡;**th sticky top 用 `--navh` CSS 變數**(JS 量測 nav 實高,nav 折行也不會蓋住表頭)。首頁另插同色票深色塊於 concept_charts.py(f-string,大括號 `{{}}`)+ dashboard.html 兩處(cron 重生成也保留):tab pill 深色+active 青色、lookup-bar 深卡(`!important` 蓋 inline 白底)、**Plotly 圖表保留白底圓角卡**(「深色框架、亮色圖卡」策略;plotly_dark 改版留待後續)。15 頁全 200 驗證。 全部由 `site_nav.nav_html()` 注入(掛統一 nav 的頁自動生效,零逐頁改表格 HTML):①**自動表格增強 `_ENHANCE_JS`**:每個 `<table>` 的 th 自動可點排序(數字/日期/字串智慧比對,`data-v` 優先;再點反向、▲▼ 指示;**th 已有自訂 onclick 的整表跳過**=不干擾 margin-scan/stock-futures 自帶多欄排序)+ 內容過寬的容器自動掛**滑鼠拖拉橫滑**(`.adrag`,自帶 `.dragx` 的跳過)+ **favicon 📈** 自動注入。②**全站統一樣式 `_SITE_CSS`**(注入於 body 內、晚於各頁 head style 故同權重勝出):頁寬統一 1100px、**表頭全站 sticky**、**深色模式**(`prefers-color-scheme: dark` 覆蓋 body/section/table/th/nav/.note/.small 等共同 class;熱力圖/徽章的 inline 色刻意保留)。③**首頁搜尋列合併**:原 5 組獨立「輸入框+按鈕」→ 單一輸入框 + 6 動作鈕(籌碼價量/融資維持率/合約負債/存貨/股東/兩波對比),Enter=籌碼價量(concept_charts.py 與 dashboard.html 同步;f-string 模板中 JS 大括號須 `{{ }}` 跳脫)。實測:extremes 點「現價」升降冪正常、margin-scan 自帶排序不受干擾(autoAttached=false)。

35. 🧭 **全站統一導航 + UX P0 修復**（2026-07-31）— ①新增 `site_nav.py`:`nav_html(current)` 產生全站一致的導航列(15 個工具連結、當前頁粗體),14 個工具頁全部改用(root 8 個模組 + app.py 內 adr/futures-basis/chip-price/money-flow/intraday-sim + warrant renderer;新增頁面只要改 `NAV_LINKS` 一處)。舊況:每頁 nav 手寫子集、互相斷鏈、futures-basis/adr 只有部分連結。②`public_url(path)`:推播訊息的公開網址(ngrok 靜態域名 `shudder-attention-musky.ngrok-free.dev`,env `PUBLIC_BASE_URL` 可覆蓋)—— option-flow/ftd 推播原帶 localhost 手機點不開,已改。③主 dashboard 補 `<meta viewport>`(原缺→手機縮成桌面版)。④`/stock-futures` **回退最近交易日**:原本當日資料未公布(15:30 前)整頁錯誤,現自動回退(最多 5 日)+ 頁頂黃條標註「顯示最近交易日 X,今日約 15:30 後更新」(指定 `--date` 則不回退)。

34. 🚀 **FTD 反彈確認日**（`/ftd`，2026-07-30 加）— 歐尼爾/IBD **Follow-Through Day**:熊市/修正結束的確認訊號。規則:①修正中(收盤自參考高點回檔 ≥`CORR_PCT`=6%) ②創低後第一根收漲=**嘗試反彈 Day 1**(防線=此前修正低點) ③盤中跌破防線=重數 ④反彈**第 ≥4 天**單日漲 ≥`FTD_PCT`=1.7%(IBD 現行;舊版 1.25)**且量增**(>前一日;台股用**成交金額**、美股用成交量)= FTD。指數:加權 TAIEX(FinMind 2004起)+ S&P500/Nasdaq(Yahoo 25y)。**內建回測**(狀態機全歷史 walk):加權 51 次 FTD **失敗率 27.5%**、S&P 39 次 25.6%、Nasdaq 66 次 28.8% —— 正好落在文獻 25-30%,演算法對得上 IBD 口徑;FTD 後 20 日:加權勝率 66.7%/+1.76%(對照 59.8%/+0.86%)、S&P 71.8%/+1.36%(對照 64.6%/+0.70%)、Nasdaq 62.1%/+1.19%(對照 63.6%/+0.99%,**無 edge**)→ edge 溫和,主要價值是「**制度化的再進場時機+明確停損線**(跌破反彈防線=FTD 失敗退出)」而非預測。歷史著名 FTD 都有抓到(S&P 2022-10-21 熊市底、2025-04-22 關稅崩後、台股 2026-04-08 +4.61% 後 60 日 +34.6%);最近 Nasdaq 2026-06-18 FTD 失敗接到本波修正。頁面:各指數當前狀態(修正中/嘗試反彈第N天/FTD確認)+ 近 20 次事件表(成敗/H20/H60)+ 白話規則。搭配:融資斷頭潮+自營收put標記「底部區」,FTD 給「反轉啟動」時機。模組 `tw_ftd.py`(`detect` 狀態機/`evaluate` 回測/`build`/`render_html`/`push_new_ftd`);cache `ftd_latest.json` + 推播去重 `ftd_pushed.json`。**cron 07:35(抓隔夜美股 FTD)+ 21:45(台股)**,「今日新 FTD」才推 **Telegram 睏霸數錢 + LINE 睏霸數錢/田尾三人幫**(`--line-to C96e...,Ca07...`,共用 line_push 模組;TG 或 LINE 任一成功即記入去重檔)。CLI `--build`/`--telegram`/`--line-to`/`--html`。

33. 📊 **選擇權法人籌碼(自營收 put)**（`/option-flow`，2026-07-30 加）— 社群實戰口徑:TXO **自營商當 put 賣方大量收權利金 = 賭不跌、轉多觀察**(「沒事不會收那麼多」)。**淨收權利金 = short_deal_amount − long_deal_amount**(FinMind `TaiwanOptionInstitutionalInvestors` TXO,單位千元→顯示億)。訊號:🟢 自營 put 淨收 ≥1億 且 ≥近60交易日 P90(異常放大);🔴 淨買 ≤−1億 且 ≤P10(大買 put 避險/偏空)。頁面:訊號橫幅 + 近60日表(加權%/自營put/自營call/外資put/外資call 淨收 + 自營put未平倉淨額)+ 白話 glossary。**已對社群訊息驗證**:2026-07-30 自營put 賣8.96−買7.26=淨收+1.70億(群訊「put回收2e」口語進位);TAIFEX 慣例夜盤(T-1 15:00→T 05:00)併入 T 日統計,故「昨晚收1e+早盤再收」與全日+1.70億相容(FinMind 無法拆盤別);當日加權盤中最高+2.8%(「早上轉多」屬實)。⚠ 自營含造市/避險腳非全方向單、非買賣訊號。**已回測**(`tw_option_flow_backtest.py`,2020-01~2026-07 共 1596 交易日、26 次🟢訊號,walk-forward 同參數):**「收put→隔天就漲」不成立** —— 隔日勝率 50%/平均 −0.38%(gap 42%/−0.21%),**低於**對照組(55.7%/+0.10%),訊號常出現在連續殺盤中隔天續殺(2024-08-02 訊號隔日 −8.35%);**真正價值在 5~10 天**:H5 勝率 69.2%/+1.32%、H10 73.1%/+2.59%(對照 59.7%/+0.52%、62.7%/+1.01%,t=2.2/3.3)—— 恐慌時 IV 飆高權利金肥、自營才收得到大錢 → 大額收 put ≈ **恐慌/波動事件標記**,之後 5~10 日常見 V 型反彈。⚠ 樣本叢集於同波恐慌(2024-08 連 4 天)+報酬視窗重疊,t 高估,當「傾向」;五分位無連續預測力(隔日);🔴 大買 put 訊號**不預測下跌**(之後反而偏漲)。回測結論顯示於頁面+推播。模組 `tw_option_flow.py`(`fetch_days`/`detect_signal`/`build`/`render_html`/`format_signal_msg`);cache `option_flow_latest.json` + `option_flow_backtest.json`。**每交易日 17:00 cron**(TAIFEX 約 15:00 公布、**FinMind 同步約 16~17 點才有當日資料**——2026-07-31 實測 15:10 尚無、17:43 已有;原 15:10 排程抓到前日資料把訊號晚一天推,已改 17:00 + **推播去重** `option_flow_pushed.json` 同訊號日只推一次),**只在訊號觸發時推 Telegram 睏霸數錢**。CLI `--build`/`--telegram`/`--html`。

32. 📅 **月份季節性 (月曆效應)**（`/seasonality`，2026-07-30 加）— 統計**月份慣性**(元月效應、農曆年作夢行情、Sell in May、紅色十月)。**A 指數月份季節性**:加權/S&P500/Nasdaq/費半/道瓊(Yahoo 月線 25 年)+ 櫃買 OTC(FinMind `TaiwanStockPrice` data_id=TPEx)+ 台指期近月連續(FinMind `TaiwanFuturesDaily` TX,每月最後交易日近月收盤,已到期合約跳過)。每個日曆月(1-12)算**上漲勝率/平均/中位報酬/標準差/最佳年/最差年**(勝率≥65% 標紅=強慣性、≤35% 標綠);當月尚未收月自動剔除。三視圖:①跨指數月平均報酬熱力表 ②各指數詳細季節表 ③加權&S&P「年×月」報酬熱力矩陣(看季節性穩定 vs 被少數大年份拉偏)。**B 台股漲停/跌停家數月份**(投機熱度季節性):FinMind `TaiwanStockPriceAdj` 全市場逐日(~2500 檔、**不含權證**,4 位數普通股過濾 = 排除 6+位權證/00開頭ETF/帶字母特別股),每日數漲停(漲幅≥9.5%)/跌停(≤-9.5%)家數,按日曆月聚合日均家數 + 漲跌停比。⚠ **台股漲跌幅 2015-06 由 7% 改 10%,跨制度家數不可比,故 B 只算 2015-06 起**。顏色遵台股慣例**紅=漲綠=跌**。模組 `tw_seasonality.py`(`_yahoo_monthly`/`_finmind_index_monthly`/`_tx_monthly`/`monthly_returns`/`seasonality_stats`/`year_month_matrix`/`_limitup_day`/`backfill_limitup`/`aggregate_limitup`/`build`/`render_html`);漲停家數逐日快取 `cache/season_limitup/{date}.json`(首建 `--backfill-limitup` 補 2015-06 起~2650 交易日,partial 也可用),結果 `cache/seasonality_latest.json`。**每月 1 號 cron 重建**(季節性變化慢、不推播)。網頁含術語白話 + ⚠ 季節性≠必然(近年結構可能改變月曆效應)、非買賣訊號。CLI `--build`/`--backfill-limitup [--start]`/`--html`。

31. 💥 **融資大減(斷頭潮)掃描**（`/margin-scan`，2026-07-29 加/改版）— 找**近5日融資餘額大減(≥8%)且股價下跌**的個股 = 斷頭/認賠賣壓宣洩(反市場低接觀察,用戶要「買發生大量斷頭的標的」)。依融資減幅%排序;🧹清洗=融資減幅>股價跌幅(浮額洗掉、常見落底)。另列**借券賣出餘額增減**(SBL空方,FinMind TaiwanDailyShortSaleBalances,綠=借券回補空方縮手)+ 個股期★ + 清洗強度 + 1日急斷 + **融資賣壓/量%** + 5種策略指南/逐欄說明。**融資賣壓/量%(2026-07-30 加,依 vocus 文章)= 近5日「融資賣出」總張 ÷5 ÷ 近5日均量 ×100%**:衡量每天融資被迫平倉賣單佔成交量比例。**關鍵用融資「賣出」(gross,MarginPurchaseSell)不用餘額淨變動** —— 淨變動會被當日融資買進沖抵而低估真實斷頭賣壓(文章例:淨減看似7.7%、實際賣出佔量14.9%);現金償還不上量不計。>15%(紅)=賣單佔量1/5、常伴連續跌停=系統性斷頭鐵證,10-15%(橙)顯著。資料:賣出 FinMind `MarginPurchaseSell`(`_margin_day` 存 [buy,bal,sell],舊快取 `ensure_sell` 自動補)、量 `TaiwanStockPriceAdj Trading_Volume`(`_vol_day`,近5日逐日快取 `cache/vol_day/`)。用法:點該欄排序找系統性斷頭,先確認此比回落+跌停打開(賣壓宣洩完)再低接。維持率=現價÷(**遞迴融資成本線**×融資成數)×100%;成本線重用 `tw_margin_monitor.compute_recursive_cost`(XQ/三竹口徑,近一年迭代、種子不敏感),融資成數上市6成/上櫃5成(同列兩口徑,維持率欄用市場成數)。資料:全市場融資買/餘額(FinMind `TaiwanStockMarginPurchaseShortSale` 逐日、快取 `cache/margin_hist/`)+ 還原收盤(重用 tw_extremes `year_prices` 快取)。市場別 TaiwanStockInfo type(twse/tpex)。模組 `tw_margin_scan.py`(`_margin_day`/`_market_map`/`scan`/`render_html`)。⚠ 用**還原收盤估、EOD 非即時**(與看盤軟體原始價/即時略異;個股維持率≠整戶維持率)→ 全市場**篩選**,單檔精確用 `/chip` 或 `tw_margin_lookup.py`(原始價+交易所即時價+FIFO 套牢)。已對單檔工具驗證成本線/公式一致(元晶成本47.12=47.12)。**每交易日 22:15 cron 重建 JSON**(融資 EOD 約21-22點公布後才有當日資料;暫不推播)。網頁含計算/口徑說明。⚠ 觀察工具非買賣訊號。

30. 📊 **一年高低極端榜**（`/extremes`，2026-07-28 加）— 全市場 4 位數個股(非 ETF)近一年:📉**距最高點跌幅最大 Top20**((現價−一年最高)/一年最高)+ 📈**距最低點漲幅最大 Top20**((現價−一年最低)/一年最低)。價格用 **還原價**(FinMind `TaiwanStockPriceAdj` 全市場單日、含還原 high/low/close,~2320 檔涵蓋率同未還原;除權息不會被當跌幅);一年高/低取 intraday 還原高低、現價取最新交易日還原收盤,回看 250 交易日(需≥60 日排除剛上市;**近 `ACTIVE_WITHIN`=2 交易日無成交者排除 = 停牌/下市櫃**,避免殘值假跌幅如 6883 微電能源停牌前 1.74)。名稱補 FinMind `TaiwanStockInfo`(含興櫃,TWSE ISIN 只有上市櫃)。模組 `tw_extremes.py`(`_trading_dates`/`_day_prices`/`compute_extremes`/`render_html`);逐日全市場快取 `cache/year_prices/{date}.json`(首建~243 次抓取、之後每日增量),結果 `cache/extremes_latest.json`。網頁兩表(高點日/低點日顯示 YY/MM/DD 分辨去年今年)+ 計算方式說明。**每交易日 20:00 cron**(盤後還原價齊)推睏霸數錢 + 田尾三人幫。⚠ 觀察工具非買賣訊號。CLI `--date`/`--top`/`--line-to`/`--json-out`

29. 🌏 **明天大盤預期**（`/market-tomorrow`，2026-07-25 加）— 用**隔夜訊號**預測隔天**加權指數(TAIEX)**方向/幅度(**%與點數**)/區間。特徵:^SOX 費半、^IXIC 那斯達克、^GSPC 標普、TSM 台積 ADR 隔夜報酬 + **台指期夜盤**報酬(15:00→05:00,把美股收盤後+亞洲+台灣本地的新聞/事件都定價進去,是隔夜新聞的即時聚合器)。滾動 OLS(前 120 日)→ 預測隔天收-收 與 開盤跳空,信心帶用**訓練殘差經驗分位數**(校準、非過度自信)。模組 `tw_market_overnight.py`(`fetch_night_returns`/`build_dataset`/`predict_next`/`backtest`/`render_html`);資料 Yahoo(美股/指數,`cache/overnight_us.json`)+ FinMind `TaiwanFuturesDaily`(台指期夜盤,`cache/tx_night.json`)。⚠ **夜盤日期慣例**:FinMind `after_market` 掛在「結束日 D」(跑 D-1傍晚→D清晨)→ 夜盤報酬 = 夜盤收(D)/前一交易日日盤收 −1、同一口契約、對齊當日開盤(誤用會 corr≈0)。**回測(walk-forward):美股+夜盤 開盤跳空方向 87.0%(高信心子集 97.6%)、收-收 76.8%,skill +19~26%**(夜盤把 84%→87%);夜盤資料未更新時自動退回美股 4 項(仍 ~84%)。⚠ **只預測大盤**:個股每日漲跌以自身雜訊(±3-5%)為主,隔夜市場成分(±1%)蓋不過,回測個股方向僅 52-55% → 故本工具刻意只做指數,個股請當背景風向。**緣起**:盤中走勢模擬(`tw_intraday_sim`)回測發現對「個股隔天方向」≈銅板(51%)、信心帶過度自信;改用隔夜訊號預測大盤才有真 edge。非買賣訊號。**每交易日 07:30 cron 推睏霸數錢 + 田尾三人幫**(盤前、美股收盤後 + 台指期夜盤已定價;cron 帶 FINMIND_TOKEN)+存 JSON 歷史 `cache/market_overnight_history/`。CLI `--backtest`/`--line-to`/`--no-night`/`--json-out`

28. 📐 **林則行矩陣選股**（`/lin-matrix`，2026-07-25 加）— 依林則行(前阿布達比主權基金經理人、日本 K 線大師，《飆股的長相》)矩陣選股法：偵測全市場個股「低量橫向箱型盤整(矩陣)→爆量突破天花板」。三條件：①盤整 ≥60 交易日(3-6個月) ②震盪幅度 **≤15%(嚴格,⭐標準矩陣;超過不算)** ③盤整期低量沉澱、突破當天量=箱型均量 2-10 倍 ④**形狀閘**(`_shape_ok`,收盤價,以視覺審計逐張校準):必須是真正的橫向震盪箱 —— 上下緣 25% 帶各觸及 ≥2 次、無內部山頭/V谷(|中段均收−兩端均收|/帶寬 ≤0.20,對稱)、非趨勢通道(|淨漂移|/帶寬 ≤0.45)、單日收盤不暴衝(≤6%,擋流動性差/崩跌)、盤末不崩跌(末段最大跌幅/帶寬 ≤0.50)。濾掉山頭(3045 台灣大)、深V(5403 中菲)、崩跌懸崖、單邊趨勢、暴衝等假箱 —— sandbox 43 檔候選僅 16 檔為真箱。每檔另列**盤整期平均 ATR**(真實區間 max(高−低,|高−昨收|,|低−昨收|) 的均值 + 佔股價%,量化盤整波動,越小越牛皮)。有掛**個股期貨**的標的標注 **📈**(取自 TAIFEX 對照 `tw_stock_futures.fetch_taifex_mapping`,可做多空/當沖)。三類輸出：🚀今日爆量突破天花板(進場點)、📦盤整中貼天花板(位階≥80%待突破)、全盤整清單 + 🏗堆疊層數(連續矩陣往上疊=鈊象式大飆股相)。模組 `lin_matrix.py`(`detect_matrix`/`classify`/`count_stacked`/`build_signals`/`render_html`)；資料 FinMind 全市場日 K「單日全市場×140天」建序列(逐日快取 `cache/lin_matrix_prices/`)。網頁含**詳細策略說明區**。**每交易日 15:00 cron 推睏霸數錢 + 田尾三人幫**(突破+貼天花板)+存 JSON 歷史。**回測 `tw_lin_matrix_backtest.py`**(v2 面板 1887 檔個股・2025-01~2026-07,收盤口徑事件研究,隔日開盤進場/還原價計酬/扣成本;重用 live `detect_matrix`/`classify` 餵 high=low=close):突破買進持有 5/10/20 日**顯著跑輸大盤**(形狀閘收緊後超額 −0.74%/−1.57%/−3.69%,t=−1.8~−3.8,IS/OOS 皆負,勝率贏大盤僅 29-44%;箱型清乾淨也救不了 edge)。⚠ **結論:當觀察/選股篩子用,非買賣訊號**(頁面已紅字揭露)。⚠ 面板無 high/low → 回測用收盤口徑;sandbox taiex.json 僅 63 日限制 live 箱型偵測,真實環境有完整歷史
27. 🔥 **個股期火熱排行**（`/stock-futures`，2026-07-24 加）— 比照群益個股期火熱排行：全市場個股期(股票期貨)按**成交量**排名，顯示標的股票代號+名稱、期貨代碼、收盤、漲跌幅、成交量、成交量增減、未平倉量、未平倉量增減 + 熱門標記(🔟漲跌幅絕對值前十、🚀量排名躍升[較前日≥30名]、〰日振幅[高-低/收]前二十、熱=量前二十)。資料 FinMind `TaiwanFuturesDaily`(全市場個股期，跨契約月加總量/未平倉；⚠ 全市場範圍查詢只回第一天→兩次單日查) + **TAIFEX `cht/2/stockLists`**(2字母期貨前綴→標的股票代號+名稱+是否股票期貨標的，快取，排除指數期)。模組 `tw_stock_futures.py`(`fetch_ranking`/`build_ranking`/`format_report`/`render_html`)。網頁**表格 12 欄皆可點標題排序**(前端 JS `_SORT_JS`,每格帶 `data-v` 真實數值避免被逗號/%/箭頭干擾,缺值 NaN 永遠沉底,再點反向;標記/象限欄按權重排)。**倉增減拆近月/遠月**(`_agg_by_futures` 記各契約月 OI,近月=最小到期月、遠月=其餘加總;⚠ 結算換月時部位由近月移遠月)。新增**量價未平倉四象限「象限」欄**(`_quadrant`:漲跌 × 總未平倉增減 → 🟥新多進場/🟧空單回補/🟩新空進場/🟦多單了結)。另加 5 欄:**基差**(近月期貨−現貨,升水+/貼水−;現貨取 FinMind TaiwanStockPrice)、**週轉**(量/未平倉,高=當沖churn/低=佈局)、**近遠價差**(次近月−近月日盤收,期限結構)、**法人淨**(特定法人[前十大交易人中的法人]個股期「所有契約」淨留倉買−賣,**全市場 ~262 檔逐檔**,源 **TAIFEX 大額交易人未沖銷部位表** `_fetch_large_trader_net` 一次查全市場、日快取 `cache/lt_inst.json`、名稱對回股票代號;⚠ 前十大特定法人 proxy、非官方未逐檔公開的完整三大法人。FinMind `TaiwanFuturesInstitutionalInvestors` 只有指數期無個股期,故棄用)、**距結算**(距近月第三個週三天數,`_days_to_settle`)。網頁附四象限圖解(`_QUAD_LEGEND`)+**各欄計算方式說明**(`_COL_GLOSSARY`,17 欄全註解)。fetch_ranking 多抓現貨(`_fetch_cash_close`)+法人(`_fetch_inst_net`);_agg_by_futures 記各月 OI/收盤拆近遠月。**每交易日 15:30 cron 推睏霸數錢群組**(Top20+標記)+存 JSON 歷史。⚠ 純排行/觀察工具、非買賣訊號。CLI `--date`/`--top`/`--line-to`/`--json-out`
26. 🎰 **權證量能觀察**（`/warrant-signal`，2026-07-22 加）— 每日盤後抓 TWSE 六類權證（`MI_INDEX?type=0999/P/B/C/X/Y`，認購/認售/牛熊/可展延），按標的現股彙總成交金額，篩「權證總額 ≥ 近20日均 2 倍」的爆量現股 + 認購/認售失衡方向 + 發行券商分布 + 主要權證明細。模組 `concept_momentum/warrant_flow.py`（抓取+彙總+日檔）、`warrant_signal.py`（爆量×失衡×方向）、`warrant_signal_backtest.py`（事件研究）、`warrant_signal_renderer.py`（頁面）。18:30 cron 每日抓取累積 `cache/warrant_flow/{date}.json`。⚠ **2026-07-21 回測（63 交易日）證實此訊號無預測 edge**：空方（認售僅認購 ~8%）從未觸發、多方無顯著正報酬（t≈0、CI95 全跨0）、收緊爆量門檻反而顯著為負（券商分銷/散戶追高的造市 confound）→ **本頁為觀察工具、非買賣訊號，回測結論在頁面紅字揭露**。**LINE 推播**（2026-07-22 加）：`warrant_push.py` 18:40 cron 把當日爆量現股 Top N 推到群組（睏霸數錢），含現股中文名 + 主要權證履約價/距到期天數，訊息最前面含無 edge 免責；收件者 `warrant_push_config.json`、沿用 `line_push.py`。**權證條款 cache**（2026-07-22 加）：`fetch_warrant_terms`/`ensure_terms` 從**元大權證網 `GetWarData.ashx` API**（POST、gzip、任何券商權證都可查）增量抓履約價/到期日/最後交易日/行使比例，靜態永久存 `cache/warrant_terms.json`（run_day 為當日 top_warrants 增量填充）；網頁 + 推播顯示履約價、距到期天數、價內外（現股收盤 vs 履約價）、行使比例。設計/回測結論見 `docs/superpowers/specs/2026-07-21-warrant-signal-design.md`
25. 📉 **兩波下殺籌碼對比**（`/chip-compare?code=XXXX`，2026-07-20 加）— 單檔兩段時期（預設 2025 春 3-8月 vs 2026 5月至今）各拆下跌段/築底段，比對 4 線：價格、**借券賣出餘額(SBL)、外資累計淨額、融資餘額**，即時 FinMind + 雙軸 SVG + 自動判讀。⚠ 單位教訓：融資 `MarginPurchaseTodayBalance` 原生為**張**（勿 /1000）、借券/法人為股（/1000 換張）。⚠ 券商分點無歷史 API，此頁不含分點。模組 `concept_momentum/chip_episode_compare.py`。緣起：3491 昇達科 2025 無量陰跌→空方低檔總攻軋空 V 轉 vs 2026 外資主導殺盤→落底期空方克制（缺軋空柴火）
24. 💰 **族群資金流** — 族群輪動觀察（/money-flow）→ `concept_momentum/`。**主排序＝成交值占比 vs 20日均（pp）**（2026-07-20 改為業界 XQ/MoneyDJ/CMoney「類股資金流」公認口徑：成交值佔比−20日均，來自真實成交金額、精確）；法人淨流金額（淨股數×收盤，近似）降為輔助欄。四象限標記 🔥/⚠/🧲/❄ 交叉占比與法人 — 例：占比大降但法人淨買=🧲低調吸收（熱度退潮、法人低接背離，舊法人金額排序會漏）

所有工具放在 `~/project/tw_stock_tools/`，cron 設定每天排程推送到 Telegram 群組。
概念動能子模組詳見 `concept_momentum/README.md`。

---

## 資料源更新 (2026-05-11)

升級 FinMind sponsor 後遷移多個工具的資料源，提升穩定性 + 統一資料源：

- **借入交易** (lending_lookup + lending_monitor) → FinMind `TaiwanStockSecuritiesLending`，解決 TWSE rate-limit 問題
- **借券賣出餘額** → FinMind `TaiwanDailyShortSaleBalances`（TWSE + TPEx 統一）
- **日線價格** (second_wave + dormant_giants + concept_momentum + limitup_signal Yahoo 部分) → FinMind `TaiwanStockPrice`
- **還券明細** (lending_lookup) — **仍用 TWSE t13sa870**（FinMind 無此 dataset）；2026-07-18 起內建 rate-limit retry（3 次、間隔 25s — 之前被限流會靜默回空、與「真無還券」無法分辨，5347 敘事因此誤報缺資料）。⚠ 其 startDate/endDate 為**借入日**區間非還券日
- **分點 BSR** (broker_monitor + broker_lookup) — **仍用 TWSE/TPEx + Playwright**（FinMind sponsor 無 per-broker dataset）

新增共用模組 `finmind_client.py`（thin FinMind v4 wrapper），所有工具透過它存取 FinMind。

---

## 1. `tw_lending_monitor.py` — 借券雷達 (SBL Radar) + 空頭撤退 (Short Retreat)

策略名：
- **借券雷達** = `--mode lending` (16:00 cron) — 議借量突增 + 利率異常
- **空頭撤退** = `--mode sbl` (21:30 cron) — 借券賣出餘額大幅減少 = 空方回補。**2026-08-01 改版(依借券事件研究)**:①單日減>10% 清單加**規模門檻「昨餘額 ≥ 發行張數 0.3%」**(舊版 3張→2張 −33% 也入選=噪音;股本%口徑因借券+融券法定上限=發行股數10%);②新增 **🎯 重空股回補**區塊(60日峰值≥股本2%、首次跌破峰值70%=回補30%+)—— 事件研究驗證這才是**回補後 5-10 日唯一超額轉正**的口徑(單日大減口徑舊回測為負超額,僅弱勢觀察);③資料改走 `tw_margin_scan._sbl_day`(逐日快取 cache/sbl_day/ 每日自動增量,供 margin-scan/研究共用);④JSON 歷史檔加 `heavy_cover` key(向後相容);推播文兩清單各附回測結論。發行張數=官方 `NumberOfSharesIssued`(tw_sbl_surge_study.load_shares 週快取)

### 用途
每日自動掃描全市場，找出兩類異常：
- **借券雷達 (議借量突增)**：議借量 > 5 日均量 × 2，且利率 <1% 或 >7%
- **空頭撤退 (借券賣出大幅減少)**：借券賣出餘額比前日減少 >10%

### 資料來源
- TWSE SBL API（`t13sa710`）：議借交易明細，上市+上櫃皆包含
- TWSE TWT93U：每日借券賣出餘額
- Yahoo Finance：股價、成交量、漲跌幅

### 核心邏輯

**議借量突增檢測**
1. 抓過去 6 個交易日的議借交易（含當日）
2. 依股票代號彙總每日議借量，利率用「成交量加權平均」
3. 計算過去 5 日平均量
4. 篩選：當日量 > 5 日均 × 2 且 利率 <1% 或 >7%
5. 為命中標的查當日股價、成交量變化

**借券賣出減少檢測**
1. 抓當日 TWT93U 餘額表
2. 針對每檔股票：當日餘額 vs 前日餘額
3. 篩選：減少 >10%（即 `(today - prev) / prev < -10%`）
4. 額外標記「借券減少且今日上漲」= 空方回補 + 股價漲 = 可能轉多訊號
5. 數值從股轉張：÷ 1000

### 使用方式
```bash
# 手動跑（列在終端機）
python3 ~/project/tw_stock_tools/tw_lending_monitor.py
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --date 20260421

# 分別執行不同 mode
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode lending   # 只跑議借
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode sbl       # 只跑借券賣出減少
python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode both      # 兩個都跑（預設）

# 推送到 Telegram
TG_BOT_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode lending --telegram
```

### 排程（crontab）
```
0 16 * * 1-5 TG_BOT_TOKEN=... /usr/bin/python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode lending --telegram >> ~/project/tw_stock_tools/lending_monitor.log 2>&1
30 21 * * 1-5 TG_BOT_TOKEN=... /usr/bin/python3 ~/project/tw_stock_tools/tw_lending_monitor.py --mode sbl --telegram >> ~/project/tw_stock_tools/lending_monitor.log 2>&1
```

- 議借：週一到五下午 4:00
- 借券賣出：週一到五晚上 9:30（借券賣出餘額要 21:00 後才公布）

### 輸出格式
分兩則訊息推送：
1. 議借異常：分「利率 <1%」和「利率 >7%」兩區塊
2. 借券賣出減少：分「借券減少且今日上漲」和「其他借券減少標的」兩區塊

推播文案已標註回測結論 (2026-07)：空頭撤退報告移除「轉多訊號」框架（回測顯示 H20 超額全負），改為觀察名單措辭；借券雷達「利率 >7%」區塊加註回測顯著看空標籤。詳見下方「借券雷達 + 空頭撤退 回測」章節。

---

## 2. `tw_lending_lookup.py` — 單檔借券狀況查詢

### 用途
輸入股票代號，印出「今日 / 昨日」的：
- 借券交易逐筆明細（定價 / 競價 / 議借）
- 還券明細逐筆（含原借入日期、借券天數）
- 借券賣出餘額（前日 / 賣出 / 還券 / 調整 / 當日 / 變化）

### 資料來源
- TWSE SBL `t13sa710`：借券交易
- TWSE SBL `t13sa870`：還券明細（含借入日期、借券天數）
- TWSE TWT93U：上市借券賣出餘額
- TPEx `/www/zh-tw/margin/sbl`：上櫃借券賣出餘額
- Yahoo Finance：即時股價（依市場自動用 `.TW` 或 `.TWO`）

### 核心邏輯
1. 依 Yahoo Finance 判斷上市 / 上櫃 → 決定用 TWSE 還是 TPEx 的 SBL API
2. 抓近 2 個交易日的借券交易，依日期分組，每筆列出
3. 抓 2025-01 至今的還券明細（因為借入日可能幾個月前），篩選「完成還券日 = 今日 / 昨日」的逐筆列出
4. 借券賣出餘額數值從股 ÷ 1000 轉張

### 使用方式
```bash
python3 ~/project/tw_stock_tools/tw_lending_lookup.py 2330
python3 ~/project/tw_stock_tools/tw_lending_lookup.py 3491 --date 20260421
```

### 輸出範例
```
2313 COMPEQ MANUFACTURING [上市]
現價: $222.50  -9.92%

━━━ 今日 (2026-04-22) ━━━
借券交易:
  合計: 129張 (3筆)
  [競價] 14張 @ 1.00%
  [議借] 80張 @ 1.75%
  [議借] 35張 @ 1.75%
還券明細: 無還券
借券賣出餘額: 無資料（21:00 後公布）

━━━ 昨日 (2026-04-21) ━━━
借券交易:
  合計: 542張 (2筆)
  [議借] 454張 @ 1.65%
  [議借] 88張 @ 1.65%
還券明細:
  合計: 716張 (3筆)
  [議借] 304張 @ 1.75% | 借於 04/14 | 7天
  [議借] 262張 @ 1.75% | 借於 04/13 | 8天
  [議借] 150張 @ 1.75% | 借於 04/10 | 11天
借券賣出餘額:
  前日餘額: 26,226張
  當日賣出: 1,286張
  當日還券: 350張
  當日餘額: 27,162張
  餘額變化: +3.6%
```

### 注意
- 還券明細（t13sa870）= TWSE SBL 平台的還券筆數
- 借券賣出餘額的「當日還券」= 所有管道（含券商/證金庫存）的還券總量
- 兩者通常不同，一個看逐筆、一個看總量

---

## 3. `tw_margin_monitor.py` — 融資維持率預警（全市場掃描）

### 用途
估算全市場每檔股票的融資維持率，篩出警戒標的（預設 <140%）。

### 估算公式
```
融資維持率 = 現價 / (加權平均買進價 × 融資成數) × 100%

融資成數：
  上市一般股：60%
  上櫃一般股：50%
  （警示股 / 管理股 / 全額交割股另計，目前未特別處理）

警戒線 140%，追繳線 130%
追繳觸發價 = 加權成本 × 融資成數 × 1.30
```

### 加權成本：FIFO 演算法
對每檔股票，從過去 1 年每日的融資資料重建「成本」（2026-07-30 由 3 個月改 1 年，視窗與價格同步拉長）：

```
For each trading day d (oldest → newest):
  today_price = 當日收盤價
  
  If 融資買進 > 0:
    add a lot: (融資買進, today_price) to queue tail
  
  reduce_amount = 融資賣出 + 融資現金償還
  While reduce_amount > 0 and queue not empty:
    oldest_lot = queue head
    If oldest_lot.volume <= reduce_amount:
      reduce_amount -= oldest_lot.volume
      pop from queue
    Else:
      oldest_lot.volume -= reduce_amount
      reduce_amount = 0

加權成本 = Σ(lot.volume × lot.price) / Σ(lot.volume)
剩餘張數 = Σ(lot.volume)  （應等於當日融資餘額）
```

**這是市場整體的估算**，不是單一投資人的真實成本。前提假設：先進先出，舊部位優先結清。

### 資料來源
- 今日快照：`openapi.twse.com.tw` + `tpex.org.tw/openapi/`（避開 www 網站的反爬限制）
- 1 年歷史：FinMind `TaiwanStockMarginPurchaseShortSale`（per-stock，每檔股票一次 API）
- 股價：Yahoo Finance 1 年日線（`fetch_yahoo_history(code, "1y")`，須覆蓋 FIFO 視窗，否則視窗前買進無收盤價會被丟棄）

### 使用方式
```bash
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_monitor.py
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_monitor.py --threshold 150 --min-balance 1000
```

### 主要參數
- `--threshold 140`：維持率警戒線（百分比），篩出 < 此值的標的
- `--min-balance 500`：融資餘額門檻（張），低於不分析
- `--max-stocks 0`：最多分析前 N 檔（0 = 全部）
- `--telegram`：推送到 Telegram
- `--date YYYYMMDD`：指定日期（預設今天）

### 快取機制
為避免 FinMind 免費版 600 req/hr 限制，資料會快取到：
```
~/project/tw_stock_tools/margin_cache/finmind_{code}_{YYYY-MM-DD}.json
```
第一次跑要抓 500+ 檔大約 10-15 分鐘（會斷斷續續因為 rate limit），
之後同一天跑會走快取，只要 1-2 分鐘。

### 已知限制
1. 融資成數用預設值，實際某些股票降低成數（40%、30%）未特別處理
2. FIFO 是市場整體加權，不等於個別投資人真實成本
3. FinMind 免費版 600/hr 限制，全市場單日首次跑可能跑不完（~600 檔後會被擋）
4. Yahoo Finance 偶爾 rate limit，失敗的股票會自動跳過

---

## 4. `tw_margin_lookup.py` — 單檔融資維持率查詢 + Cohort 分析

**網頁版**：`/margin-lookup?code=XXXX&method=fifo|lifo|proportional`（dashboard 快速查詢列「💳 融資維持率」，2026-07-07 加；同 CLI 輸出 + 術語說明）

### 用途 (2026-07-20 改版)
輸入股票代號，輸出：
- **主指標：XQ/三竹口徑「遞迴融資成本線」**（市場資料商同款算法：`今日成本 = (昨日成本×(餘額−買進) + 收盤×買進) ÷ 餘額`，賣出以均價移除、全歷史遞迴自 2018 起）— 無「舊部位成本未知」黑洞，種子不敏感（實測 2018~2025 任一起點收斂相同）。維持率同時給**五成（券商實務，上櫃/高價股常見）與六成（法規上限，金管會歷次令上市上櫃均六成）兩口徑**＋各自追繳價 — 實際成數依券商與個股而異，真實值落在區間內
- **現價用交易所 MIS 即時報價**（盤中即時、收盤後=當日收盤；修 Yahoo 404 fallback 的 stale 價問題，來源標示在輸出）
- 第二段：FIFO 視窗成本（**近 1 年**可追蹤批次，明示非整體。2026-07-30 由 3 個月改 1 年 `FIFO_WINDOW_DAYS=365`：融資套牢常 >3 個月，3 個月視窗常讓深套部位算不出維持率(None)；價格/融資歷史皆自 2018 起、拉長視窗有足夠資料。實測 2609 陽明 3 個月→0 可追蹤批次(None)、1 年→2874 張 $50.79(近遞迴 $52.48);3231 緯創 6887→10712 張。**視窗前更舊的部位仍是黑洞 → 看遞迴成本線**）
- **批次（cohort）分布**：把融資餘額按進場日拆成多批，看不同進場價的維持率（資料商沒有的差異化視角）
- 主要批次明細（佔總餘額 ≥5% 的大量進場日）
- 教訓：改版前 headline 把「3 個月視窗批次成本」當整體維持率，3491 於 2026-07-20 跌停日顯示 180% 安全，但遞迴成本線口徑實為 131%(六成)~157%(五成) — 差一整個風險等級

### 為什麼要做 cohort 分析？
單一加權平均會掩蓋風險。例如 2313 整體維持率 151%（看似安全），但拆開後追蹤量 92% 都已在警戒區（130-140%），只是被舊部位拉高平均。Cohort 才是真實的風險分布。

### 三種扣減規則（`--method`）
餘額減少時，要把減少量歸因到哪一批 cohort？三種假設：

| Method | 假設 | 適用情境 |
|--------|------|----------|
| `fifo`（預設） | 老批先扣（先進先出） | 最常見假設：老倉達到停利停損先出場 |
| `lifo` | 新批先扣 | 假設新進場恐慌賣壓較強 |
| `proportional` | 全部按比例扣 | 中性視角，無方向性 |

同一檔股票用不同 method 結果差異巨大。建議搭配使用做壓力測試。

### Cohort 演算法（balance-change 法）
```
For each trading day d (oldest → newest):
  delta = today_balance - prev_balance

  If delta > 0:
    add cohort {date: d, volume: delta, price: today_close}

  If delta < 0:
    reduce = -delta
    Match against cohorts using selected method:
      fifo: reduce from oldest
      lifo: reduce from newest
      proportional: scale all by (1 - reduce/total)
    若仍有剩餘，從 legacy（觀察期前的舊部位）扣

當前活躍 cohorts → 各自算維持率 → 分桶（<130, 130-140, 140-150, 150-170, 170+）
```

**Legacy 概念**：1 年觀察期之前就存在的部位，因為沒有當時的成本資料，無從估算維持率。獨立顯示「舊部位 X 張」。

### 使用方式
```bash
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_lookup.py 2313
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_margin_lookup.py 3035 --date 20260422
```

### 輸出範例
```
3035 FARADAY TECHNOLOGY [上市]
現價: $168.50  -5.87%

【融資維持率估算】
加權成本: $179.00 (FIFO 過去 1 年)
融資餘額: 15,780 張
融資成數: 60%
估算維持率: 156.9%  🟢 尚可（150-170%）

【關鍵價位】
140% 警戒價: $150.36  (再跌 10.77%)
130% 追繳價: $139.62  (再跌 17.14%)

【近期融資買進（最近 5 筆）】
  04/16: 買 366 張 @ $156.50
  04/17: 買 423 張 @ $159.00
  04/20: 買 1,683 張 @ $174.50
  04/21: 買 1,734 張 @ $180.00
  04/22: 買 1,317 張 @ $179.00
```

### 狀態分級
- 🔴 危險（<140%）
- 🟡 警戒（140-150%）
- 🟢 尚可（150-170%）
- ✅ 安全（>170%）

---

## 5. `tw_broker_monitor.py` / `tw_broker_lookup.py` — 主力雷達 (Smart-Money Radar)

策略名：**主力雷達** (盤後 18:00 cron) — 分點買賣超 + 融資連動 = 主力建倉雙確認

### 用途
找出疑似「用融資做短線」的券商分點：在過去 N 天連續買超某檔，且這幾天該股的融資餘額也同步增加，且分點當日淨買 vs 當日融資淨增量呈正相關。

### 核心邏輯

對每一檔目標股票：
1. 抓近 N 天（預設 5）BSR 分點資料 + FinMind 融資歷史
2. 對每個分點計算：
   - **連續買超**：N 天內 ≥3 天買超 + 每天買超 >當日 5% 總量
   - **融資同步**：N 天累積融資餘額淨增加 > 0
   - **相關係數**：分點當日淨買 vs 當日融資淨增量的 Pearson 相關 ≥ 0.5
3. 三項都符合 → 列入「疑似用融資做短線」名單

### 資料源

| 資料 | 來源 | CAPTCHA 處理 |
|------|------|--------------|
| 上市分點買賣量 | TWSE BSR `bsr.twse.com.tw/bshtm/` | 圖片 CAPTCHA → ddddocr |
| 上櫃分點買賣量 | TPEx `brokerBS.html` | Cloudflare Turnstile → patchright + Xvfb |
| 融資餘額歷史 | FinMind `TaiwanStockMarginPurchaseShortSale` | - |

**重要限制**：BSR 與 TPEx 兩邊都只有「當日」資料，沒有歷史。所以必須每天 cron 抓取累積，第 5 天起分析才有完整視窗。

### CAPTCHA 突破方法

**TWSE BSR（簡單圖片）**：
- 套件：`pip install ddddocr`
- 解碼成功率約 95%，失敗自動重試
- 搭配 Session 維持 ASP.NET ViewState

**TPEx（Cloudflare Turnstile）**：
- 套件：`pip install patchright`（playwright fork，反偵測）
- 系統：`apt install xvfb`（虛擬顯示器）
- 必須用 `headless=False` + Xvfb 才能讓 Turnstile 自動解鎖（純 headless 會被 Cloudflare 偵測拒絕）
- 用 `browser.new_page()` 預設 context，**不要**自訂 viewport/locale/UA

### 使用方式
```bash
# 單檔查詢（需要至少 2 天 BSR 歷史 cache）
FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_broker_lookup.py 2313

# 全市場掃描 + 推送 Telegram
TG_BOT_TOKEN=xxx FINMIND_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_broker_monitor.py --top-n 200 --telegram
```

### 掃描標的選擇

預設每天掃兩組標的的聯集：
1. **Top N 大融資餘額**（預設 200）：用 TWSE/TPEx OpenAPI 取得當日融資餘額排序前 N 檔
2. **概念動能強勢族群成分股**（過門檻 + 20 日報酬 Top N）：讀 `concept_momentum/cache/results/analysis_{today}.json`，取通過正式選股門檻（`passes_gate=true`）的族群，按 20 日報酬 (`ret_20d`) 排序，選前 N 個（預設 8）族群的成分股加入掃描範圍。舊結果檔沒有 `passes_gate` 欄位時自動 fallback 評分 ≥ 70 的邏輯。

效果：避免某檔不在融資 Top 200 但在強勢概念中的個股漏抓 BSR 快取。可用 `--no-concept-strong` 關閉、`--concept-min-score` 調整評分門檻（fallback 用）、`--concept-top-themes` 調整強勢族群數（預設 8）。

### 排程
```
0 18 * * 1-5 ... tw_broker_monitor.py --top-n 200 --telegram
```
週一到五傍晚 6:00（BSR 約 17:30 公布）累積資料並執行分析。第 5 個交易日起分析開始有效。
注意：concept_momentum cron 設在 17:00 跑，會把 `analysis_{today}.json` 存好讓 18:00 broker_monitor 讀取。

### 已知限制
1. BSR 沒有歷史，需從今日起累積
2. Cloudflare Turnstile 偶爾偵測（10-20% 失敗率，會自動重試）
3. 無法區分「分點買進」中現股 vs 融資的比例 — 只能用相關性做 inference
4. 公開資料源都沒有 per-(分點 × 現股/融資) 細項：FinMind v4/v3 完整 enum (~100 datasets) 掃過，沒有此維度的 dataset (`TaiwanStockTradingDailyReport` 不存在)。連贊助 tier 也沒有。實務替代：HiStock 有「分點融資估計」但是 inference 結果，不完全準。

### 回測（`tw_broker_radar_backtest.py`）

主力雷達靠分點 BSR，BSR 無歷史 API → 不能重算歷史訊號。改用 cron 每天存下的實際訊號輸出
(`broker_radar_history/YYYYMMDD.json`) 做事件研究：每個被點名的 (股票, 日)，量它之後 H 日報酬
vs 大盤 vs 同期隨機股票日基準 (edge)。

**v2 重點改動**：
- **進場預設隔日開盤** (`--entry next`)：訊號 18:00 才出，隔日開盤是最早可實現的進場價；
  v1 用訊號日收盤進場是理想化（不可實現）。`--entry signal` 保留理想化版本供對照。
- **date-matched 基準**：baseline 改為與事件同日期的隨機 100 股票平均超額（對齊市場狀態），
  取代 v1 的全期隨機採樣。
- **bootstrap 95% CI + t-stat**：判讀 edge 是否顯著 — CI 全正才顯著，含 0 = 不確定。

**重要告示**：
> 事件由已部署的訊號版本產生，改訊號參數（BSR 閾值、融資相關性門檻等）後歷史事件不可比。
> 累積至少半年以上歷史後再回測才有統計意義。

**CI 判讀**：
- CI 全正 = 有統計顯著 edge；CI 含 0 = 方向參考，無統計結論
- 樣本 n < 30 → CI 非常寬，結論僅供方向參考（⚠ 警語會印出）
- edge_mean 已扣除成本（0.471%）

```bash
# 跑回測（預設 next=隔日開盤）
python3 ~/project/tw_stock_tools/tw_broker_radar_backtest.py \
  --json-out concept_momentum/cache/broker_radar_backtest.json

# 查看結果
open http://localhost:5000/broker-radar-backtest
```

---

## 6. `tw_broker_history_lookup.py` — 個股分點歷史查詢（HiStock 爬蟲）

### 用途
TWSE BSR 只開放當日資料，本工具用 HiStock 補足歷史視角，輸出指定股票過去 N 天累積買/賣超的 Top 30 分點。

### 資料來源
HiStock `histock.tw/stock/branch.aspx?no=<code>&day=<N>`
支援 N：7, 10, 14, 30, 60, 90, 180, 270, 365

### 使用方式
```bash
python3 ~/project/tw_stock_tools/tw_broker_history_lookup.py 3035            # 預設 10 天
python3 ~/project/tw_stock_tools/tw_broker_history_lookup.py 2330 --days 30 --top 20
```

### 輸出
- 期間（from-to 日期）
- 買超 Top N 分點：分點名稱 + 買張 + 賣張 + 淨買 + 60 天均價
- 賣超 Top N 分點：同上

### 限制
- HiStock 限制每張表 Top 30 分點，無法取得全部分點
- 累積買賣超，無單日分布
- 屬非官方頁面，HiStock 改版會壞

---

## 7. `tw_us_correlation.py` — 美台聯動 (US-TW Beta)

策略名：**美台聯動** (CLI) — β 調整後 TW 個股 vs US peer 相關性，扣除大盤 β 後仍同步的真聯動

### 用途
找出台股哪些標的真的跟著指定美股 peer 動。可指定一個概念內掃描，或直接對全市場（34 個概念去重共 ~190 檔）跑相關性。

典型用途：
- 「想做 NVDA / BE / AMD 行情但只能買台股 → 找最高相關度的影子股」
- 「驗證某概念是不是真的跟著 narrative 美股動」（e.g., 台股 ASIC 跟 AVGO 連不連動？）
- 「同一家公司 ADR vs 母股，相關性能多高？」（TSM vs 2330 = +0.47，揭示日線級別 ADR 連動上限）

### 資料來源
Yahoo Finance（query1.finance.yahoo.com）— 同 `concept_momentum/data_fetcher.py`，台股自動加 `.TW` / `.TWO` 後綴，美股直接用 ticker。資料範圍依 window 自動切換：window ≤ 100 用 `6mo`，101–200 用 `1y`，> 200 用 `2y`。

### 計算邏輯（β 調整版，預設）
1. 抓近 6 個月或 1 年日線
2. 算每日 daily return: `(close_t - close_{t-1}) / close_{t-1}`
3. **β 調整**：
   - 台股 vs `^TWII`（台灣加權）算 β（線性迴歸斜率：`Cov(s,m)/Var(m)`）
   - 美股 vs `^GSPC`（S&P 500）算 β
   - excess_return = stock_return - β × market_return
   - 目的：去除「全球 risk-on 共漲」的雜訊，留下真正的個股 idiosyncratic 連動
4. **時差對齊**：TPE D ↔ US D-1（TPE D 反應的是前一晚 US 收盤，US D 的 session 在 TPE D 之後才發生）
5. Pearson 相關係數於指定視窗（預設 240 個 TPE 交易日，約 1 年；可用 `--window 60` 看近期 narrative）

### 兩種模式
| 模式 | 用途 | 數值範圍 | 風險 |
|------|------|---------|------|
| **β 調整（預設）** | 找真正 idiosyncratic 連動 | 通常較低（0.2–0.5） | 數字小看似不顯著 |
| `--raw` | 直觀「美股漲台股也漲」 | 通常較高（0.4–0.7） | 含全球 β，可能誤判共漲為連動 |

實例：1605 華新 vs AMD
- raw：+0.35（看起來中等相關）
- β 調整：+0.19（揭示其實沒實質連動，只是兩邊各自吃了 AI risk-on）

### 使用方式
```bash
# 單一概念查詢（預設用該概念內建美股 peer）
python3 ~/project/tw_stock_tools/tw_us_correlation.py ASIC自研晶片

# 指定特定 peer
python3 ~/project/tw_stock_tools/tw_us_correlation.py ASIC自研晶片 --peer MRVL

# 全市場掃描（推薦）— 不漏掉跨概念的高相關股；預設 240 天視窗
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer NVDA

# 看近期 narrative（60 天視窗）
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer BE --window 60

# 跑 raw 看共動，含全球 β（小心雜訊）
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer BE --raw

# 列出所有概念與預設 peer mapping
python3 ~/project/tw_stock_tools/tw_us_correlation.py --list
```

### 預設美股 peer mapping
腳本內 `US_PEERS` dict 涵蓋全部 34 個概念，例如：
- ASIC自研晶片 → AVGO, MRVL, ALAB
- AI伺服器_ODM → DELL, HPE, SMCI
- AI伺服器_電源 → VRT, ETN, GEV
- NVIDIA供應鏈 → NVDA
- HBM記憶體 → MU
- CPO_矽光子 → ANET, CIEN, COHR
- 半導體設備 → AMAT, LRCX, KLAC, ASML
- SiC功率元件 → ON, WOLF
- 重電_電網 → ETN, GEV, HUBB

每季可依市場焦點微調此 dict。

### 解讀門檻
| 範圍 | 圖示 | 意義 |
|------|------|------|
| ≥ 0.6 | 🟢 強相關 | 直接 narrative driver，幾乎可當 proxy 交易 |
| 0.3–0.6 | 🟡 中等 | 有 narrative 連動，可作為 hedge 候選 |
| < 0.3 | ⚪ 弱 | 自己走自己的，台美連動弱 |

注意：β 調整版數字普遍較低 — `β-adj 0.3 ≈ raw 0.5` 的訊號強度。

### 已知限制
- 日線資料的時差對齊已盡量處理（TPE D ↔ US D-1），但仍有 ADR 溢價、隔夜 gap、匯率影響
- `--raw` 模式的高相關常常是「共同蹭 macro narrative」，要用 β 調整版驗證
- ADR 同公司（TSM vs 2330）的相關性上限約 +0.47（時段錯開、資訊分裂）— 不要期待 1.0
- 視窗選擇影響大：60 天反映近期 narrative，180/240 天反映中長期；兩者差距大代表近期有 regime change（如台船 60 天 +0.46 vs 240 天 +0.14，60 天為短期巧合）
- 預設 240 天是為了過濾掉短期雜訊，得到較穩定的相關性畫面；要看近期變化用 `--window 60`

---

## 8. `tw_turnaround_screener.py` — Turnaround 篩選器

### 用途
找出同時滿足三條件的「基本面改善 + 量能進場 + 空方撤退」標的：
- 毛利率近 4 季向上（基本面改善）
- 量能放大（資金開始流入）
- 借券賣出餘額減少（空方回補）

對應的市場 narrative：「公司轉好 + 法人買進 + 之前空它的人開始認輸」 — 經典 turnaround setup。

### 過濾條件（可調）
| 條件 | 預設值 | 意義 |
|------|--------|------|
| `--gm-pp` | 1.5 | GM_Q-0 - GM_Q-3 ≥ N pp（4 季累積增幅） |
| `--gm-qoq` | 2 | 4 季中至少 N 次 QoQ 增長 |
| (固定) | 4 季 GM 均 ≥ 0% | 排除任一季 GM < 0% 的股票（避免處分損失/單季虧損等會計異常造成的假信號，例如 2527 宏璟 Q-2 GM -482%） |
| `--vol-ratio` | 1.3 | 近 20 日均量 / 近 60 日均量 ≥ N |
| `--sbl-decline` | 0.95 | 近 10 日借券賣出餘額均 / 前 30 日均 ≤ N |
| (固定) | 收盤 ≥ MA60 | 收盤價站上季線（quarterly MA） |
| `--ma-accel-days` | 5 | 曲率比較窗口（近 5td 斜率 vs 前 5td 斜率） |
| `--ma-curv-ratio` | 0.5 | 曲率寬鬆度。slope_recent ≥ ratio × slope_earlier。1.0=嚴格加速、0.5=允許動能減半（預設）、0.0=只要求斜率為正 |

### 資料來源
| 指標 | 來源 |
|------|------|
| 季毛利率 | FinMind `TaiwanStockFinancialStatements`（Revenue + GrossProfit） |
| 量能 | Yahoo Finance（6mo 日線） |
| 借券賣出餘額 | FinMind `TaiwanDailyShortSaleBalances` 的 `SBLShortSalesCurrentDayBalance` |
| 借券交易量（proxy） | FinMind `TaiwanStockSecuritiesLending` aggregated daily |

注意：
- 融券餘額（`MarginShortSalesCurrentDayBalance`）也會抓但只顯示作參考，不納入過濾。設計上「借券賣出餘額」是法人空方主戰場，融券是散戶/投機部位，兩者邏輯不同。
- 借券餘額（gross outstanding）TWSE 不公開逐日資料，本工具改抓「借券交易量」作為 proxy 顯示。借券賣出餘額減少 + 借券交易量也減少 = 空方收手；借券賣出餘額減少但借券交易量增加 = 法人換手，需警覺。
- **GM 快取 TTL**：季毛利率快取在財報公告死線前後窗口（3/25–4/10、5/5–5/25、8/5–8/25、11/5–11/25）內採 3 天 TTL（快速同步新季報），其餘平時 21 天 TTL。原先 30 日統一快取會導致新季報最多晚 30 天才生效。

### 使用方式
```bash
# 預設掃描全市場 TWSE + TPEx 4 位數普通股（~3000 檔，首跑 ~2-4 小時，後續快取後 ~30 分）
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py

# 只掃 concepts.json (~190 檔，快很多，10-15 分)
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py --universe concepts

# 調整門檻
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py \
  --gm-pp 2.0 --vol-ratio 1.5 --sbl-decline 0.90

# 指定股票
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py \
  --universe 2330,2454,3491

# 用 FinMind token 加速（避免 free tier rate limit）
python3 ~/project/tw_stock_tools/tw_turnaround_screener.py \
  --token $FINMIND_TOKEN
```

### Universe 選項
- `--universe all`（預設）：FinMind TaiwanStockInfo 撈全 TWSE + TPEx，篩 4 位數純數字代號（避開 ETF 0050、REITs 01001T、權證等），約 3000 檔。Universe 列表 cache 7 天。
- `--universe concepts`：concepts.json 內 ~190 檔（已分類在主題板塊，掃描較快）
- `--universe 2330,2454,3491`：指定股票測試

### 輸出
1. 表格列出通過所有 3 條件的標的（按綜合分數排序）
2. 每檔詳細：
   - 4 季毛利率 + Δpp + QoQ 次數
   - 量能 20d / 60d
   - 借券賣出 10d 均 vs 前 30d 均
   - （參考）融券同期變化

### 限制
- FinMind free tier 有 rate limit（600/小時），全市場掃約 8-15 分鐘；用 token 可加速
- 季財報有 lag：Q1 財報通常 5 月公告，Q4 財報 3-4 月，掃出來的 GM 可能不是即時最新季
- SBL 餘額只反映「沒回補的部分」，不直接等於「主力多空態度」 — 配合分點/法人籌碼一起看更準
- 預設 universe 是 concepts.json (~190 檔)；`--universe all` 全市場尚未實作

### 實例（2026-04-29 跑出 6 檔，加上 D 過濾後）
3105 穩懋 GM 16.7→31.8% / Vol 1.30x / SBL -10.9% / MA60 +42%（趨勢最強）
4576 大銀微 GM 35.8→38.4% / Vol 1.64x / SBL -47.5% / MA60 +46%（趨勢強，融券 +246% 散戶反向）
3491 昇達科 GM 50.6→58.6% / Vol 1.55x / SBL -16.2% / MA60 +7%（多頭剛確立）
6173 信昌電 GM 22.3→26.8% / Vol 1.62x / SBL -26.3% / MA60 +22%
3406 玉晶光 GM 30.9→34.3% / Vol 1.56x / SBL -31.3% / MA60 +13%（融券 -85% 最乾淨）
6166 凌華 GM 34.5→36.7% / Vol 1.96x / SBL -5.7% / MA60 +16%

被 D 過濾掉：2314 台揚（GM 剛轉正但價格未站上季線）

---

## 9. `tw_limitup_signal.py` — ABCD 接力型訊號分析

### 用途
對輸入的股票清單做 ABCD 四面向訊號評分。兩種使用模式：

**模式 1: Standalone 漲停掃描**
無 `--codes` 參數時，掃當日全市場漲停股 (≥9.5%)，回看前一交易日訊號。
適合事後分析「今日漲停的前日訊號是否齊備」。

**模式 2: Layer 2 — 接力型過濾 (cron 用)**
指定 `--codes` 或 `--codes-file` 時，對提供的清單 (通常來自 Layer 1 turnaround screener) 做 ABCD 評分，
找出 Layer 1 候選中「明日續攻機率高」的子集。

設計動機：4576 大銀微系統 (2026-04-30 漲停) 的事後回顧顯示前一日已有三項一致訊號
(漲停接力 + 借券回補 + 外資集中買進)，可被前瞻識別。本工具將該模板抽象為可複用的 ABCD 訊號層。

### 盤前/盤後 mode 語意（2026-07 新增）

`--mode {auto|premarket|postclose}`（預設 auto）：

| mode | 使用情境 | anchor 位置 | A/D 視窗說明 |
|------|----------|-------------|--------------|
| **postclose** | standalone 漲停掃描 (`--date`) | `px[-1]` = 漲停日本身 | A 看 px[-2]/[-3]/[-4]；D 前日 = px[-2] |
| **premarket** | Layer 2 盤前 (`--codes/--codes-file`，07:30 cron) | `len(px)` (「今天」尚未發生) | A 看 px[-1]/[-2]/[-3]；D 前日 = px[-1] |
| auto | 有 `--codes/--codes-file` → premarket；否則 → postclose | — | — |

`tw_daily_screen.py` 的 cmd2 傳 `--mode premarket`（顯式，不靠 auto）。

⚠ **2026-07 之後的 `abcd_score` 與之前版本不可直接比較**：盤前模式 A/D 現在納入最新一根K棒（昨日），舊版漏看該K棒，分數基準不同。

### 四項訊號（各 1 分，滿分 4）
| 訊號 | 條件 | 含義 |
|------|------|------|
| **A 漲停接力** | anchor 前 3 根 K 棒任一日漲幅 ≥ +5% 或 ≥ +9.5% (漲停)，且 anchor 前一日盤中未崩 ≤-4% | 已有突破/強勢動能，今日漲停是接力而非孤立反彈 |
| **B 借券回補** | 借券賣餘 3d 均 / 前 5d 均 ≤ 0.97 或前日單日 ≤ -3% | 空單在止血、空方信心動搖 |
| **C 籌碼集中** | 7 天累積外資 (高盛/摩根/瑞銀/野村/JPM/花旗/美林等) ≥ 2 家 in top10 買超，或 top5 買超合計 ≥ top5 賣超合計 | 主流法人/外資進駐 |
| **D 量能蓄勢** | anchor 前一日量 / 20d 均量 ≥ 1.0 或 / 60d 均量 ≥ 1.5 | anchor 前一日已有資金提前進場 |

### 輸出分群
- **4/4 ⭐⭐⭐⭐ 全訊號**：四項都滿足，最高品質前瞻訊號
- **3/4 ⭐⭐⭐**：三項滿足，明確訊號
- **2/4 ⭐⭐**：兩項滿足，列摘要 (one-line, 用旗標顯示哪些訊號)
- **≤1/4**：純拉抬，僅列代碼（事後無前瞻訊號）

推播文案已標註回測結論 (2026-07)：「≤1/4」分組標題加註「ABD<2 抱20日顯著負超額 — 避開」，對應下方「Layer 2 ABD overlay」回測章節。

### 資料來源
| 指標 | 來源 |
|------|------|
| 漲停清單 | TWSE `MI_INDEX` (上市) + TPEx OpenAPI `tpex_mainboard_daily_close_quotes` (上櫃) |
| 個股 OHLCV | Yahoo Finance (`.TW` / `.TWO`，3 個月) |
| 借券賣出餘額 | FinMind `TaiwanDailyShortSaleBalances` (data_id 可在 register tier 用) |
| 7 天分點 | HiStock `branch.aspx` 爬蟲 (與 `tw_broker_history_lookup` 共享 parser) |

### 使用方式
```bash
# Standalone: 掃當日全市場漲停股
python3 ~/project/tw_stock_tools/tw_limitup_signal.py

# Layer 2 模式: 對指定股票清單評分
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes 4576,3491,3406

# Layer 2 模式: 從 JSON 檔吃 codes (通常 Layer 1 產生)
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes-file /tmp/layer1.json

# 只列 ≥3/4 (更嚴格 Layer 2)
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes-file ... --min-score 3

# 推送到 Telegram (--bot-token / TG_BOT_TOKEN)
TG_BOT_TOKEN=xxx python3 ~/project/tw_stock_tools/tw_limitup_signal.py \
  --codes 4576 --telegram

# 回測指定日期
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --date 2026-04-30

# 自訂報告標題 (供 wrapper 用)
python3 ~/project/tw_stock_tools/tw_limitup_signal.py --codes ... \
  --header "🎯 Layer 2 — 自訂分析"
```

通常不直接 cron，由 `tw_daily_screen.py` 包裝呼叫。直接 standalone 排程也可：
```cron
0 18 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=... /usr/bin/python3 \
  /home/kun/project/tw_stock_tools/tw_limitup_signal.py --telegram
```

### 性能
- 全市場 (~50 檔漲停) 平行掃描 (6 workers)：約 3-4 分鐘
- HiStock 為主要瓶頸 (1-2 sec/req)，cache 設計按日期，當日重跑會即時返回

### 限制
- HiStock 7 天累積買賣超是時間範圍 (~4/22-4/29)，不是純粹「前一天」籌碼，但能補足 TWSE BSR 只有當日資料的限制
- 4 項訊號是經驗法則 (基於 4576 case study)，未做大規模回測樣本內外驗證
- D (量能) 對近期已大跌補量的股票 (e.g., 4576) 偏嚴，可能漏判 — 屬已知 false negative
- **C 籌碼集中 — 歷史回看無效**：HiStock `branch.aspx` 無日期參數，僅能查「現在」的 7 日視窗。`--date` 回看歷史日時 C 訊號一律回傳 `(無籌碼)` = 0 分（2026-07 起止血；之前的歷史快取若已存入可能含錯誤資料，不信任 `--date` 回看的 C 分）。

### 實例（2026-04-30 全市場掃描，50 檔漲停 / 12 檔 ≥3/4 訊號）
**4/4 全訊號（4 檔）**
- 3707 漢磊 (借券賣餘 -29.2%, 外資 6 家買超 6,639 vs 賣 1,489)
- 3016 嘉晶 (前日量 5.1x 60d, 外資 5 家 GS+UBS+Merrill 包辦)
- 4991 環宇-KY (借券賣餘 -3.7%, 前日量 5.6x 60d)
- 2417 圓剛 (借券賣餘 -19.0%, 前日已連兩漲停)

**3/4（8 檔，含 4576 大銀微系統）**：A+B+C 但量能未爆 / 或 A+C+D 但借券未明顯回補

---

## 11. `concept_momentum/` — 族群熱力 (Theme Heatmap)

策略名：**族群熱力** (盤後 17:00 cron) — 各概念族群動能評分 + 領漲/領跌 + Rerating + 業務轉型偵測

詳細文件見子模組：[`concept_momentum/README.md`](concept_momentum/README.md)

簡要：
- **動能評分**：每概念依 20d 漲幅 / 廣度 / 量比 / RS / 持續天數綜合打分 (0-100)
- **強弱分組**：≥70 強勢 (顯示 🟢 多 leaders + 🔴 空 laggards 配對提示)，<30 弱勢
- **Rerating**：β 調整後與其他概念相關性 ≥ 自己概念 +0.10 → 可能改題材
  - **穩定性過濾** (預設開啟): 須在過去 3 日內連續 ≥2 次指向同一目標概念才推送，避免單日雜訊。穩定後的訊號會顯示「[連續 N 日]」標籤
  - **「兩條沉船」過濾 A/B/C** (預設開啟): 用實際數據驗證後加入的三道強度檢查。
    - **A. 目標族群評分 ≥30** — 排除「目標也是弱勢族群」的偽 rerating（鴻準與 CXO 都在跌、節奏類似 → β-adj corr 高 ≠ 業務轉型）
    - **B. 目標族群為強勢** — score ≥50 或 RS_20d > 0，確認資金真的在流入該目標族群（不是兩個一起被棄）
    - **C. 原屬族群已脫鉤** — own_max_corr < 0，要求股票真的「反向」脫離原概念，不只是相關性下降
  - 推送會在 candidates 後顯示「目標 75 分 RS+18.0%」等強度資訊，並列出排除統計
  - 快取於 `concept_momentum/cache/rerating_history/{date}.json`（A/B/C 在過濾**之前**已存檔，保留歷史訊號密度）
- **業務轉型**：新聞主題與原概念差 ≥1.5x，且 ≥2 個不同關鍵字 (避誤判)
- 推送 Snapshot PNG + Trend PNG + 4 則文字摘要到 Telegram
- **大盤寬度 (Market Breadth)**：dashboard.html 最上方分頁，13 欄 × 60 個交易日。寬度池 = 上市+上櫃 普通股 4 位代號 (~2,300 檔)。包含加權指數 / 漲跌幅 / 股價>20-50-200MA% / 200日新高 / 三大法人 (拆 4 欄) / 融資餘額 + 增減
  - **資料源**：FinMind sponsor tier (`TaiwanStockPrice` 全市場 + `TaiwanStockTotalInstitutionalInvestors` + `TaiwanStockTotalMarginPurchaseShortSale`)
  - **已知 quirk**：FinMind 法人/融資 dataset 在查 `start_date=end_date=X` 時會回傳 X 與 X+1 兩天的資料；fetcher 已加 `if row['date'] != date: continue` 過濾，避免 off-by-one（commit a4b45f1）
  - **歷史 backfill**：首次部署需 200 天 universe 快取，`market_breadth.backfill_universe()` 自動執行 (~3-5 分鐘)；之後每天 cron 1 個 FinMind 呼叫即增量更新
- **快取**：`concept_momentum/cache/market_universe/{date}.json` (全市場日 OHLC) + `concept_momentum/cache/market_breadth/{date}.json` (計算結果)，皆 gitignored
- **🎯 主力雷達歷史榜**：dashboard 第二分頁，10 日視窗。每日 18:00 cron 跑出的主力分點+融資連動結果累積，依「綜合分數 = 連續天數 × (log(Top 分點淨買+1) + sqrt(融資增量)) / 2」排序，Top 30
- **🌅 盤前訊號**：dashboard 第三分頁，10 日視窗。上下兩段顯示轉機接力 (TR ABCD) 與強勢股第二波，含連續入榜天數。強勢股第二波表格自 2026-07-08 起加「層」欄 (⭐/◐/▽ 分層標記，詳「強勢股第二波」節)，排序依 latest_date desc → tier (⭐>◐>▽>未標記) → today_vs_peak asc；自 2026-07-09 起再加「借」欄 (借↓/借↑ 借券急跌變化標記，詳「籌碼確認（借券急跌變化）」節)
- **🌙 借券動向**：dashboard 第四分頁，5 日視窗。上下兩段顯示借券雷達 (議借爆量) 與空頭撤退 (借券賣餘大減)，依時間/變化幅度排序
- **歷史榜快取**：5 個新 dir — `concept_momentum/cache/{broker_radar_history,turnaround_relay_history,second_wave_history,lending_radar_history,short_retreat_history}/{date}.json`，皆 gitignored；歷史由 cron 累積，無 backfill

### 族群熱力回測（`tw_concept_backtest.py`）

驗證族群動能評分是否具有前向預測力；三變體比較：複合加權(A)、純動能 ret_20d(B)、動能+門檻過濾(C，正式推送採用)。

**跑回測（快取命中，無網路呼叫）：**
```bash
FINMIND_TOKEN=$(crontab -l | grep -o 'FINMIND_TOKEN=[^ ]*' | head -1 | cut -d= -f2) \
  python3 tw_concept_backtest.py \
  --json-out concept_momentum/cache/concept_backtest.json
# → 開啟 http://localhost:5000/concept-backtest 看三變體比較表 + 權益曲線
```

**方法摘要：**
- **IC 計算**：允許重疊觀察（每 5d rebalance），加 block bootstrap 95% CI 校正序列自相關。
- **L2 權益曲線**：使用**非重疊**網格（步進 = max(rebalance, H)），確保 total/max_dd/calmar 可信。
  - 舊版重疊灌水問題：H=20d × rebalance=5d → 每筆持倉重複計入 4 次，H=20 total 舊值 ~334% 為 ~4× 灌水。
  - 修正後 H=20 total 下降至 ~72%（strategy）；這是正確值，非退化。
- **流動性過濾 parity**：`ret_20d_score` 改用成交額加權概念指數（同正式版 `analyze_all`）；L2 選股前加 `filter_liquid_stocks`（同正式版 `analyze_concept`）。

**2025-01 起回測結果摘要（新版，非重疊 L2）：**

| 指標 | strategy (A) | benchmark (B) | filter (C) |
|------|-------------|--------------|------------|
| IC @H5 | +0.128 [+0.075,+0.179] | +0.121 | +0.076 |
| IC @H10 | +0.162 [+0.105,+0.229] | +0.138 | +0.099 |
| IC @H20 | +0.194 [+0.127,+0.278] | +0.142 | +0.140 |
| L2 total @H5 | +81.6% | +94.5% | +83.2% |
| L2 total @H10 | +101.5% | +119.7% | +113.5% |
| L2 total @H20 | +72.2% | +52.9% | +110.2% ✓ |
| Calmar @H10 | 5.30 | 12.01 | **12.48** |
| ret/vol @H10 | 0.45 | 0.54 | **0.60** |

**filter vs benchmark 結論：**
- **H5/H10**：filter total 略低於 benchmark（+ 流動性過濾縮小池子），但 H10 ret/vol 與 Calmar 均高於 benchmark，顯示風險調整後 filter 仍具優勢。
- **H20**：filter total (+110.2%) 遠高於 benchmark (+52.9%)，且 H20 L2 CI 下界正 ✓，統計顯著。
- **整體**：廣度/量能**當門檻過濾**（排除項）在 H20 明顯加值；H5 短期差異不顯著。正式推送繼續採用 C 變體。

**舊值 vs 新值對照（重疊灌水說明）：**

| 變體 | H20 total 舊 (重疊) | H20 total 新 (非重疊) | 倍率 |
|------|---------------------|----------------------|------|
| strategy | ~334% | +72.2% | ~4.6× |
| benchmark | ~260% | +52.9% | ~4.9× |
| filter | ~280% | +110.2% | ~2.5× |

舊版 `rebalance=5d × H=20d` 每個持倉日被計入 4 個 bucket，total/max_dd/calmar 全部失真。現已修正為每個持有期各自獨立觀察。

**導航結構 (2026-07-07 重整)**：上方「🔍 單檔快速查詢」列 = 4 個帶股號輸入框的工具 (籌碼價量/合約負債/存貨/前十大股東)；nav 四群組 = 族群動能 (6 分頁) / 訊號監控·依時段 (盤前/借券/主力雷達/成效) / 🧪 策略回測·事件研究 (5 頁) / 即時工具 (盤中模擬/ADR/期貨基差)。每個入口全站僅出現一次。

### 本機看儀表板

```bash
# 手動啟動 Flask（開發用，預設 port 5000）
python3 ~/project/tw_stock_tools/concept_momentum/app.py
# → 開啟 http://localhost:5000/
```

### systemd 自動化（生產用，WSL 開機自啟）

兩個 user systemd unit 已在 `~/.config/systemd/user/`：
- `concept-dashboard.service` — Flask 永久跑在 :5000
- `ngrok-tunnel.service` — ngrok 對外公開 :5000

啟用 lingering 一次（之後重開 WSL/Windows 都會自動跑）：
```bash
sudo loginctl enable-linger $USER
systemctl --user enable concept-dashboard.service ngrok-tunnel.service
systemctl --user start concept-dashboard.service ngrok-tunnel.service
```

查當前 ngrok 公網網址：
```bash
curl -s http://localhost:4040/api/tunnels | python3 -c 'import sys,json;[print(t["public_url"]) for t in json.load(sys.stdin)["tunnels"]]'
```

Free-tier ngrok 每次重啟會發隨機網址；如要固定網址需升級 ngrok Pro 並設 reserved domain。

---

## 10. `tw_daily_screen.py` — 每日兩層篩選工作流（轉機接力策略）

### 用途
每日盤前 07:30 (Mon-Fri) 自動執行兩階段篩選 — 名為「**轉機接力**」策略：

**Layer 1** (`tw_turnaround_screener.py`)
基本面 + 技術面初篩 — 毛利率改善 + 量能放大 + 借券回補 + 季線多頭
全市場 ~3000 檔 → 數檔到數十檔 candidates

**Layer 2** (`tw_limitup_signal.py --codes-file <layer1.json>`)
對 Layer 1 候選做 ABCD 接力型訊號評分 — 找出「明日續攻機率最高」子集

兩層結果都推送 Telegram，使用者隔日可用實際漲跌「後照鏡」驗證 Layer 2 嚴格度，
逐步調整 ABCD 訊號條件。

### 流程
```
07:30 cron (盤前 1.5 hr)
  ↓
Layer 1 — 轉機 (~1 min warm cache, ~5-10 min cold cache)
  ├ tw_turnaround_screener --json-out /tmp/layer1.json --telegram
  │   毛利率↑ + 量能↑ + 借券↓ + 季線多頭排列 + 排除 GM<0%
  │   → 推送 Layer 1 表格摘要到 TG
  ↓
Layer 2 — 接力 (~1-2 min, 視 Layer 1 候選數)
  ├ tw_limitup_signal --codes-file /tmp/layer1.json --min-score 2 --telegram
  │   ABCD 接力訊號評分 (漲停接力/借券回補/籌碼集中/量能蓄勢)
  │   → 推送 ABCD 分級結果到 TG (4/4/3/4/2/4)
  ↓
完成 (盤前可看完，9:00 開盤前布局)
```

「**轉機接力**」(Turnaround Relay) — Layer 1 找已轉機的標的池，Layer 2 從中
挑出技術面準備接力突破的子集。資料用前一交易日收盤，盤前推給使用者參考布局。

### 使用方式
```bash
# 預設模式：兩層都跑、推送 TG
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_daily_screen.py

# 不推 TG (測試)
python3 ~/project/tw_stock_tools/tw_daily_screen.py --no-tg

# Layer 2 更嚴格 (只看 ≥3/4)
python3 ~/project/tw_stock_tools/tw_daily_screen.py --layer2-min 3

# 用 concepts universe (~190 檔，更快)
python3 ~/project/tw_stock_tools/tw_daily_screen.py --universe concepts
```

### 排程（crontab）
```cron
# 每天盤前 07:30 (Mon-Fri) 兩層篩選 — 轉機接力策略
30 7 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=... /usr/bin/python3 \
  /home/kun/project/tw_stock_tools/tw_daily_screen.py \
  >> /home/kun/project/tw_stock_tools/daily_screen.log 2>&1
```

### 為什麼分兩層？
- **Layer 1 嚴格但靜態**：基本面 + 量能 + 借券 — 「值得關注」的池子，可能 4-30 檔
- **Layer 2 動態 + 接力型**：在 Layer 1 池子內找「明日突破機率高」— 更積極
- **後照鏡學習**：用實際漲跌結果驗證 Layer 2 訊號是否能 predict，逐步調 ABCD threshold

### 實例（2026-04-30，--universe concepts）
Layer 1 → 4 檔候選：3491 昇達科, 4576 大銀微系統, 3406 玉晶光, 6166 凌華

Layer 2 → 4576 大銀微系統 3/4 ⭐⭐⭐ (今天剛好漲停 ✅ 印證)
- A 近 3 日內漲停 +9.9%
- B 前日借券賣餘 -3.7%
- C 外資 3 家齊買 (高盛/MS/JPM)
- D 量能未過門檻 (大銀微平日成交量低)

3491 昇達科 / 3406 玉晶光 各 2/4，未達 ≥3/4 接力門檻。

---

## 12. `tw_dormant_giants.py` — 沉睡巨人篩選器

### 用途
找出「曾經 5 倍股、跌幅 ≥30%、沉睡 ≥5 年、近期長時間量縮窄幅整理」的標的。
這類股票的特徵：
- 過去有故事、有資金推升過 → 證明商品/題材有想像空間
- 但現在已被市場徹底遺忘，籌碼洗淨、套牢盤消化
- 波動率被壓到底、量也縮到底 → 沒人關心
- 若有新催化事件 (產業景氣回暖、新題材、業務轉型)，向上爆發力大且阻力小

### 五項過濾 (各須滿足)
| 條件 | 預設 | 意義 |
|------|------|------|
| **A 曾 5 倍股** | peak/peak前低點 ≥ 5x | 還原收盤峰值除以峰前低點，且峰前需有 ≥3 年資料才算數 (避開 Yahoo 起點即峰值的假訊號) |
| **B 跌 ≥ 30%** | current ≤ 70% × peak | 從峰值修正 |
| **C 峰值 ≥ 5 年前** | peak_date ≤ today − 5y | 退潮已久 |
| **D 近 5 年無炒作** | 5y max/min < 3x，任 120td 滑窗 max/min < 1.5x | 確認沒被再炒過 |
| **E 量縮震盪** | 60d 振幅 < 10%，60d 量 ≤ 75% × 3y 平均量 | 真正的窄幅整理 |

預設由原 10x / 跌 50% 放寬到 5x / 跌 30%（實證 10x+50% 全市場僅 0-2 檔太嚴；5x+30% 約 5 檔較合理）。
若想看更嚴格名單可加 `--min-peak 10 --max-current-pct 0.5`。

### 資料源
| 資料 | 來源 |
|------|------|
| 還原股價 | Yahoo Finance `adjclose` (含 split + dividend；多數 case 也涵蓋減資)。FinMind `TaiwanStockPriceAdj` 需付費，本工具用 Yahoo 替代 |
| Universe | FinMind `TaiwanStockInfo` (與 turnaround_screener 共享 universe_all 快取，4 位數普通股) |

注意：Yahoo TW 資料起點 ~2007，2007 前已達峰的個股 (e.g. 6244 茂迪 2006 高點 >900) 可能漏抓。
透過 `--min-pre-peak-years` (預設 3) 強制要求峰前 3 年資料，自動排除這類「資料截斷」假訊號。

### 使用方式
```bash
# 預設掃全市場
python3 ~/project/tw_stock_tools/tw_dormant_giants.py

# 推送 Telegram
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_dormant_giants.py --telegram

# 放寬倍數 (預設 10x 太嚴可改 5x)
python3 ~/project/tw_stock_tools/tw_dormant_giants.py --min-peak 5

# 放寬量縮條件
python3 ~/project/tw_stock_tools/tw_dormant_giants.py \
  --max-60d-range 0.15 --vol-decline-ratio 1.0
```

### 性能
全市場 ~3000 檔，cold cache (Yahoo 抓 18 年) ~5-10 分鐘 (6 workers 平行)；
warm cache 後續查詢 < 1 分鐘 (cache 7 天)。

### 排序邏輯
按 `沉睡年數 × (0.20 − 60d 振幅) × (0.40 − 量比) × 倍數/10` 由大到小排序，
即「越久沉睡 + 越窄整理 + 越大歷史倍數」越優先。

### 實例（2026-05-03 全市場掃描，預設 5x / 跌 ≥30%）
篩選漏斗：2,141 → A:1,327 → AB:757 → ABC:220 → ABCD:19 → **ABCDE:5 檔**

| 代號 | 名稱 | 倍數 | 跌幅 | 沉睡 | 60d 振幅 | 60d/3y 量比 |
|------|------|------|------|------|---------|------------|
| 9944 | 新麗 | 6.6x | 72% | 11.8y | 8.3% | **0.30x** |
| 2496 | 卓越 | 14.9x | 60% | 9.0y | **5.5%** | 0.58x |
| 6195 | 詩肯 | **31.9x** | 52% | **12.4y** | 8.5% | 0.73x |
| 1474 | 弘裕 | 9.9x | 45% | 5.9y | 6.4% | 0.60x |
| 5487 | 通泰 | 26.4x | 38% | 6.6y | 9.6% | 0.71x |

亮點：
- **9944 新麗** 量縮 + 跌幅 + 沉睡三項皆領先，綜合品質最高
- **2496 卓越** 60d 振幅 5.5%，五檔中波動最緊
- **6195 詩肯** 31.9x 倍數最高、沉睡 12.4 年最久
- **5487 通泰** 26.4x 高倍數、2019 後一路冷卻

### 限制
- Yahoo 資料對減資 (capital reduction) 的還原可能不完美 — 邊角案例需手動驗證
- 「沉睡」≠「會漲」— 工具只是過濾「有可能 turnaround 的池子」，不是買入訊號
- ABCDE 五關全過的標的數量稀少 (台股全市場每天大約 0-5 檔)，建議搭配基本面研究

---

## 13. `tw_second_wave.py` — 強勢股第二波篩選器

### 用途
抓「強勢上漲數月 → 1-2 週無法突破 → 急殺 15-25% → 開始反彈」的標的，
搶**第二波發動**的入場點。主力洗籌碼後再拉一波的高勝率 setup。

### Pattern 四階段
1. **Phase 1 強勢底盤**：峰前 6 個月已大漲 (預設 ≥30%)
2. **Phase 2 高點停滯**：峰值前後 1-2 週無法再突破新高
3. **Phase 3 急跌洗盤**：1-2 週內急跌 15-25% (恐慌爆量、短線散戶被洗出)
4. **Phase 4 第二波啟動**：低點後 1-10 td 反彈，量能轉強但還沒破前高

### 七項過濾 (各須滿足)
| 條件 | 預設 | 說明 |
|------|------|------|
| F1 強勢底盤 | rally ≥ 30% | 峰前 6m 累積漲幅 |
| F2 高點在近 | peak ≤ 60 td 內 | 峰值落在最近 3 個月 |
| F3 急跌幅度 | 15% ≤ drop ≤ 25% | peak → trough 跌幅 |
| F4 急跌時長 | 5-15 td | peak → trough 持續天數 |
| F5 反彈進行中 | trough 1-10 td 前 / bounce ≥ +5% | 已反彈但不老 |
| F6 量能甦醒 | 近 3d 均量 / 急跌期均量 ≥ 0.7 | 急跌期常爆恐慌量，反彈期不需爆量但不能萎縮 |
| F7 還沒新高 | 今 < 0.98 × peak | 避免太晚進場已破前高才追 |

### 資料源
Yahoo Finance 9 個月日線 (.TW / .TWO)，cache 1 天 (pattern 是快速移動的，不適合長 cache)。

### 使用方式
```bash
# 全市場 (預設)
python3 ~/project/tw_stock_tools/tw_second_wave.py

# Telegram 推送
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_second_wave.py --telegram

# 個股驗證 pattern
python3 ~/project/tw_stock_tools/tw_second_wave.py --universe 2313

# 放寬底盤門檻 (前漲 ≥20% 也算)
python3 ~/project/tw_stock_tools/tw_second_wave.py --rally-min-gain 0.20

# 嚴格版：跌 20-25%、反彈量比 ≥ 1.0
python3 ~/project/tw_stock_tools/tw_second_wave.py \
  --drop-min 0.20 --recovery-vol-ratio 1.0
```

### 排程（crontab）
```cron
# 每天盤前 07:40 (Mon-Fri) 強勢股第二波掃描
40 7 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=... /usr/bin/python3 \
  /home/kun/project/tw_stock_tools/tw_second_wave.py --quiet --telegram \
  >> /home/kun/project/tw_stock_tools/second_wave.log 2>&1
```
與「轉機接力」(07:30) 錯開 10 分鐘 — 開盤前 1.5 hr 同時看到兩套策略結果。

### 分層標記 (⭐/◐/▽，2026-07-08 加入)

依「子群分析」節結論落地的**標記**（不改篩選、名單成員不變）：

```python
TIER_BIG_TURNOVER_NTD = 1_100_000_000   # 20d 均成交額門檻 (~P67)
TIER_EARLY_TVP = 0.88                    # 距前高門檻 (today/peak < 0.88 = 反彈早期)
```

| 層 | 定義 | 20d 超額 (2026-07 子群回測) |
|----|------|------|
| ⭐ | 距前高 <88%（早期）且 20d 均成交額 ≥11 億（大額） | +11.9%（n=52，CI 全正） |
| ◐ | 距前高 <88%（早期）但成交額未達門檻 | 未獨立驗證 |
| ▽ | 距前高 ≥88%（已近前高，現行大多數訊號屬此層） | ≈0（無 edge） |

`turn20_ntd` = 最近 20 根 K 棒 mean(volume × close)。`classify_tier(today_vs_peak, turn20_ntd)` 為純函式，見 `tw_second_wave.py`，測試在 `tests/test_second_wave_tier.py`。

### 排序邏輯（2026-07-08 起）
排序改為 **`today_vs_peak` 升冪**（距前高越遠、反彈越早期，排越前面）— 取代原本的 `second_wave_score` 排序。
原因：2026-07 子群回測發現 `second_wave_score` 排序**無鑑別力**（Spearman IC 全樣本 ≈0，三分位不單調，詳下方「子群分析」節）。
`score` 函數本身保留（僅供 `--json-out` 的 `second_wave_score` 欄位 JSON 相容，不再驅動排序）。

### 性能
全市場 ~3000 檔，cold cache (Yahoo 9m) ~1-2 分鐘 (6 workers 平行)；
warm cache 後續查詢秒級。

### 實例（2026-04-30 全市場掃描，9 檔候選）

| 代號 | 名稱 | 前漲 | 跌幅 | 反彈 | 今/峰 | 量比 |
|------|------|------|------|------|------|------|
| 4991 | 環宇-KY | **457%** | 21.3% | +18.6% | 93% | **5.16x** |
| 3163 | 波若威 | **551%** | 19.7% | +10.1% | 88% | 1.52x |
| 6588 | 東典光電 | 474% | 21.6% | +15.6% | 91% | 0.75x |
| 2313 | 華通 | 299% | **25.0%** | +14.0% | 85% | 0.95x |
| 3234 | 光環 | 300% | 18.5% | +11.8% | 91% | 0.75x |
| 3437 | 榮創 | 129% | 23.1% | +15.4% | 89% | 1.06x |
| 1528 | 恩德 | 118% | 18.0% | +15.7% | 95% | 0.83x |
| 5243 | 乙盛-KY | 85% | 21.4% | +5.7% | 83% | 2.56x |
| 4760 | 勤凱 | 74% | 17.4% | +8.1% | 89% | 0.84x |

亮點：
- **4991 環宇-KY** 反彈量比 5.16x 最強，前漲 457%、目前 93% 接近前高
- **3163 波若威** 前漲 551% 倍數最高
- **2313 華通** 用戶最初提的參考案例，工具確認過 pattern

**使用時機與限制**（2026-07-08 起於 `/second-wave-backtest` 頁與盤前訊號分頁顯示）：edge 集中在動能市（2022-24 OOS ≈0、2022 熊市為負，大盤轉弱停用或降倉）；持有約 20 交易日（短抱期望為負）；樂透型分布須分散持有；候選 ≠ 買入訊號。regime 即時監測 = 訊號成效頁 ⭐ 分層桶。

### 子群分析（2026-07-07，502 episodes，2025 訓練 / 2026 驗證）

固定 20 天持有下，兩年方向一致且全樣本 CI 顯著的特徵：

| 子群 | n | 超額20d | 95% CI | 中位數 | 贏大盤率 |
|------|---|---------|--------|--------|---------|
| 距前高 <88% | 142 | +5.75% | [+1.5,+10.0] | **+1.7%** | — |
| 距前高 ≥88%（現行 72% 的訊號） | 360 | +0.05% | [-2.7,+2.9] | -5.7% | — |
| <88% × 日均成交額 ≥11 億 | 52 | **+11.86%** | [+5.0,+19.0] | +7.2% | 65% |
| <88% × 跌深 20-25% | 106 | +5.38% | [+0.4,+10.3] | +3.3% | 56% |
| 反面組（≥88%×淺跌×小額） | 193 | -0.72% | [-4.1,+2.8] | -6.9% | 39% |

- 兩年不穩定（2025/2026 反轉）故**不可用**：量比、反彈幅度、反彈天數、前漲幅度。
- `second_wave_score` 排序**無鑑別力**（Spearman IC 2025 +0.10 / 2026 -0.04 / 全 +0.00，三分位不單調）— 名單排序目前無資訊含量。
- **❌ OOS 驗證結果（2026-07-08，面板拉到 2022，1330 episodes）**：<88% 規則在 2022-2024 **不成立** — <88% 組 exc20 -0.05% vs ≥88% 組 -0.37%（無差異），⭐ 組 2023 +4.2%（n=17）但 2024 **-2.4%**（n=37）、2022 樣本不足。整個策略在 2022-2024 三年皆 ≈0 超額（全部 -0.25% [-1.4,+1.0]）。結論：**⭐/◐/▽ 分層是 2025-26 動能市的 regime 現象，非結構性規則 — 濾網維持 0.98 不收緊**，標記保留作透明化與 forward-test 用途，判讀時需知其 regime 依賴性。
- ⚠ Caveats：事後子群挖掘（~20 種切法）、combo 的 2025 子樣本過小（n=11-13）無法獨立確認；正確用法是先「標記分層」讓成效追蹤器 forward-test，或把面板拉到 2022-2024 做真 OOS，再考慮改正式濾網。
- **2026-07-08 落地**：已加上 ⭐/◐/▽ 分層標記（見上方「分層標記」節）+ 排序改 `today_vs_peak` 升冪，取代無鑑別力的 score 排序。訊號成效追蹤器 (`run_outcomes.py`) 新增 `sw_tier_buckets` 分桶統計，forward-test 這個分層結論（詳「訊號成效追蹤」節）。

### 籌碼確認（借券急跌變化，2026-07-09 加入）

急跌是「洗盤」還是「真跌」的籌碼判別：量測急跌期（`peak_date` → `trough_date`）借券賣出餘額變化 % —
`sbl_chg = (bal@trough / bal@peak − 1) × 100`（bal@X = 日期 ≤ X 的最後一筆餘額）。**只加標記，不改篩選**。

```python
SBL_TAG_DROP = -5.0   # ≤ -5% = 借↓ (回補)
SBL_TAG_RISE = 5.0    # ≥ +5% = 借↑ (增加)
```

`classify_sbl_tag(sbl_chg_pct)` 為純函式，見 `tw_second_wave.py`，測試在 `tests/test_second_wave_sbl_tag.py`。
資料源：`finmind_client.fetch_short_sale_balances`，快取 `second_wave_cache/sbl_{code}_{today}.json`（當日 TTL，每候選 1 次呼叫）。
Fail-open：無 token / API 失敗 / quota ban → 該檔標 `—`，名單照常出（不影響掃描）。

episode 條件化回測（急跌期借券賣餘變化 × 20 日超額報酬）：

| 資料窗 | n | 回補 (≤-5%) | 持平 | 增加 (≥+5%) |
|--------|---|-------------|------|-------------|
| 2025-26（動能市） | 529 | **+6.51%**［95% CI +2.9,+10.4］贏 51% | +0.21% | **-0.86%**（中位 -4.5%，贏 37%） |
| OOS 2022-24 | 556 | +2.22% | +0.45% | -1.00%（單調性成立，CI 跨 0；2022 年增加組 **-5.88%**［CI 全負］；2023 反例：回補 -1.2% vs 增加 +0.6%） |

不對稱結論：「借↑（空方加碼）」是跨年較穩定的**避開訊號**；「借↓（空方回補）」是 2025-26 動能市放大的加分訊號，**2023 年有反例**。
定位 = **標記 + forward-test**，不改變第二波篩選條件。融資餘額變化已測**無鑑別力**（不採用）。

### 動能市增進研究 — null results 記錄（2026-07-09）

除借券標記（見上）外，另兩個方向已測試並**否決**，記錄以免重複踩坑：

1. **Regime gate（事前判斷動能市）— 六種指標全數失敗**：TAIEX>MA60、TAIEX>MA60+上揚、寬度≥55%/50%、漲停家數 20d 均 ≥23/30、策略自體健康度（滾動 60 檔已實現 exc20）≥0/+2%。每一種的 ON 條件下 ⭐ 組在 2022-24 仍為負（-1.2~-3.4%）；池化「ON 有效」全是 2026 年份組成偏差（2026 幾乎全年 ON）。註：2024 也是指數多頭年但策略無效 → 「動能市」非指數趨勢可捕捉，最接近的特徵是漲停家數（2026 均 58.8 vs 2022-24 的 19-28），但該水準 2025 前不存在、無法 OOS 驗證。**唯一可靠的 regime 監測仍是訊號成效頁的 ⭐ 分層桶（事後追蹤）**。
2. **出場規則 — 固定 20 天勝過全部四種聰明出場**（2025-26 ⭐ 組：固定 +10.0% vs 停損 trough +7.5% / 移動停利 10% +6.2% / 停損+移停 +4.5% / cap40 +5.8%）。此類高波動股收盤觸發式出場全是 whipsaw：停損專門賣在低點（跌破 trough 後常反轉）、移停把大贏家半路砍掉。**結論：不要幫這個策略加機械式停損** — 風控靠分散與 20 天時間出場。

### 限制聲明
- 純技術面 pattern，未做基本面驗證 — 使用者需自行確認「基本面沒轉壞」
- 急跌可能是利空 (基本面轉壞)、政策 (產業限制)、或主力洗盤 — 三者需區分
- 候選 ≠ 買入訊號，是「pattern 已成形的池子」，需搭配當日量價、消息面決策
- **除權息 guard**：peak 到今日若有除權息交易日，視為除權缺口而非主力洗盤，自動剔除

推播文案已標註回測結論 (2026-07)：報告頭部加註「20日持有型 setup，對同日基準有 edge 但中位數為負（樂透型）— 單檔部位宜小、分散」，對應下方 v2 回測結論。

### 回測 v2（`tw_second_wave_backtest.py`）

**進場口徑**：訊號日**隔日還原開盤價** (`--entry next_open`)。訊號在 07:40 盤前產生，隔日開盤是最早可實現的成交價；v1 使用訊號日收盤進場，把無法預知的隔夜跳空算進報酬（口徑不可實現）。v1 → v2 數字不可直接比較。

**報酬衡量**：採**還原價** (aopen/aclose)，跨除息持有期不再低估報酬。

**除權息 guard**：偵測窗 (peak_date → 訊號日] 內有除權息交易日的 episode 剔除，避免未還原收盤的除權缺口偽造 Phase 3 急跌訊號。剔除數記錄為 `n_skipped_div`。

**成本模型**：`cost_roundtrip_pct(discount=0.6, slippage_bp=0.0) = 0.471%`（手續費 6 折 + 證交稅，零滑價假設）。

**統計**：bootstrap 95% CI（5000 次重抽，seed=7）、t-stat、超額中位數、分年拆解（2025 / 2026）。

**基準**：與每個事件**同日期**隨機抽 k=100 檔股票的平均超額（date-matched baseline），比「隨便買一檔」多多少算 edge。

**CI 判讀**：`exc_ci` 含 0 表示該 horizon 無統計顯著 alpha；`edge_ci` 全正才算訊號真有 edge。

```bash
# 跑回測（使用已建立的 bt_cache/backtest_prices_v2.json，無需網路）
python3 tw_second_wave_backtest.py \
  --json-out concept_momentum/cache/second_wave_backtest.json

# 背景執行（1895 檔 × 370 天，約 2-5 分鐘）
nohup python3 tw_second_wave_backtest.py \
  --json-out concept_momentum/cache/second_wave_backtest.json \
  > bt_cache/swbt.log 2>&1 &

# IS/OOS 切窗（--is-end 給定 YYYYMMDD 上界，自動切 IS/OOS 兩窗，結果多一個 result.windows 鍵，不影響原本 schema）
python3 tw_second_wave_backtest.py --is-end 20260331 --json-out /tmp/sw_iso.json
```

**v2 回測結果摘要**（2025-01-02 ～ 2026-07-06，全市場 1895 檔）：

| H | n | 超額均 | 95% CI | t | 淨超額 | edge_mean | edge_ci |
|---|---|------|--------|---|-------|-----------|---------|
| 5d | 502 | -0.69% | [-1.62, +0.31] | -1.43 | -1.16% | -0.05% | [-0.96, 0.92] |
| 10d | 501 | +0.08% | [-1.32, +1.52] | +0.11 | -0.39% | +1.17% | [-0.22, 2.58] |
| 20d | 502 | +1.66% | [-0.61, +4.11] | +1.39 | +1.19% | +4.54% | [+2.29, +6.94] |

除權息剔除：77 episodes（占訊號 1828 日 × cooldown 去重前）。

**結論**：
- H=5/10d：CI 含 0，無統計顯著 alpha
- H=20d：超額 CI 含 0（不顯著）；但 edge_ci=[+2.29, +6.94] 全正，表示持有一個月時訊號相對隨機基準有統計顯著 edge
- 第二波是「抱一個月」的 setup，不是短打；均值右偏（靠少數大贏家），中位數為負

---

## 環境變數

| 變數 | 用途 | 來源 |
|------|------|------|
| `TG_BOT_TOKEN` | Telegram Bot 推送 | `~/.claude/channels/telegram/.env` |
| `FINMIND_TOKEN` | FinMind API | 個人 token |

---

## 檔案位置總覽

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

## 轉機接力回測 (`tw_turnaround_backtest.py`)

Layer 1 四濾網（ABCD）的首次系統性回測，採 point-in-time 事件研究法。

### 方法

**資料與 PIT 規則**

- 毛利率：FinMind `TaiwanStockFinancialStatements`；`date` 欄是季末日，非公告日
- 財報**可用日**（law-deadline rule，保守）：

  | 季末   | 可用日  |
  |--------|---------|
  | 3/31   | 5/15    |
  | 6/30   | 8/14    |
  | 9/30   | 11/14   |
  | 12/31  | 翌年 3/31|

  多數公司提早公告，故此規則**低估** edge（不高估）。
- 量能/季線：v2 price panel 未還原 close/volume，與正式篩選器同口徑
- 借券餘額：as-of 截斷到事件日 t

**訊號重建**
import 正式 `tw_turnaround_screener` 純函數逐日跑；episode 去重採 cooldown=max_horizon，同一波只取首次進場。

**Layer 2 ABD overlay**
在每個 Layer 1 事件日計算 A（漲停接力）/ B（借券回補）/ D（量能蓄勢）三個 overlay 訊號（C 訊號需分點歷史無公開記錄，誠實跳過），依總分 ≥2 vs <2 分兩組，比較前向超額報酬差異。

**進場假設**：訊號日隔日還原開盤（07:30 盤前推播後最早可成交時間）。

**IS/OOS 切窗**：`--is-end 20260331` 把回測切成 IS（`--start` ~ `--is-end`）/ OOS（`--is-end` 翌日 ~ 期末）兩窗，各自輸出 `summarize_events` 摘要於 `result.windows.{IS,OOS}[h]`；不給則行為與 schema 完全不變（供參數敏感度掃描腳本用）。

### Headline 數字（2025-01-01 起）

> 首跑結果（`tw_turnaround_backtest.py --start 2025-01-01`，2026-07-06 完成）：

- **Episodes**：613（universe 1895 檔，GM 可過關 1482 檔）
- **H=5d**：超額 +0.17% CI [-0.53, 0.87] t=0.48 淨 -0.30%；ABD≥2: +0.29% vs ABD<2: +0.06%
- **H=10d**：超額 +0.15% CI [-0.94, 1.28] t=0.27 淨 -0.32%；ABD≥2: +0.59% vs ABD<2: -0.28%
- **H=20d**：超額 -1.14% CI [-2.65, 0.39] t=-1.46 淨 -1.61%；ABD≥2: +0.12% vs ABD<2: -2.39% ★

**★ 關鍵發現**：ABD overlay 分組差異在 H=20d 最為顯著：
- ABD<2 超額 -2.39% CI [-4.24, -0.42]，t=-2.42，CI 全負 → 統計顯著的負 edge
- ABD≥2 超額 +0.12%（CI 含 0，非顯著），但明顯優於 ABD<2 組（差值 +2.51pp）
- 解讀：Layer 1 單獨信號不足，**ABD<2（低 overlay 分數）應視為迴避警號**

### Live-History Overlap 驗證

取 `concept_momentum/cache/turnaround_relay_history/2026*.json` 的 layer1_passed 記錄（37 個交易日，1192 組 (date, code) 對），
與回測同日事件集合比對：overlap = **5.1%（61/1192）**。

差距來源（低 overlap 的結構性解釋）：
1. **Cooldown 去重（最主要）**：回測對每檔股票施加 cooldown=20 天，實際運行不去重；若一檔連過 10 天，回測只計 1 次，live 計 10 次 → overlap 分母膨脹 10×
2. **法定死線 vs 實際公告**：回測用保守法定死線，多數公司早於死線公告，live 可先看到最新 FS
3. **面板口徑微差**：v2 面板快取 vs 盤前即時快取時間戳差異

> 本 overlap 偏低（＜30%）主要為設計上的保守性（cooldown + PIT），非訊號失準。

### 限制

去重前逐點保真度驗證：對 live 歷史 1,169 個 (股,日) 以回測 PIT 邏輯重算四濾網，88.7% 全數通過（A 90.1% / B 99.1% / D 99.7% / C 99.7%）；殘差主因為 PIT 法定死線保守性（設計如此）與 live 端 GM 快取過期（已由財報季 TTL 修正改善）。5.1% episode overlap 為 cooldown 稀釋後的預期值。

1. **C 訊號缺失**：Layer 2 只含 A/B/D，若 C（籌碼集中）有效，ge2 組 edge 可能被低估
2. **樣本期間偏短**：面板 start=2025-01-01，約 1.5 年，多頭友善期；空頭盤 edge 未知
3. **PIT 保守**：財報用法定死線，比多數公司實際公告晚，回測 edge 低估
4. **滑價假設**：成本 0.471% 假設零滑價，轉機股流動性偏低時實際成本更高

Dashboard 頁面：`/turnaround-backtest`（仿第二波頁，多 Layer2 ge2/lt2 對照表）

---

## 借券雷達 + 空頭撤退 回測 (`tw_lending_backtest.py`)

借券監控系統（`tw_lending_monitor.py`）兩個盤後推播策略的系統性回測，採事件研究法（point-in-time）。

### 方法

**兩個訊號定義（對齊 live 規則）**

| 策略 | 訊號條件 | 分組 |
|------|----------|------|
| 空頭撤退 | 當日 SBL 餘額 / 前日 − 1 ≤ −10%（前日餘額 ≥200 張，排除小基數雜訊） | all / up_only |
| 借券雷達 | 當日議借量 > 前 5 日均量 × 2（爆量）且量加權利率帶 | low_rate (<1%) / high_rate (>7%) |

**資料來源**
- SBL 餘額：FinMind `TaiwanDailyShortSaleBalances`（快取 7 天）
- 議借紀錄：FinMind `TaiwanStockSecuritiesLending`（`transaction_type='議借'`）
- 價格：v2 price panel（`TaiwanStockPrice/Adj`，含 aopen/aclose 還原價）

**進場假設**：訊號日隔日還原開盤。統計/成本/基準同 `backtest_lib`（成本 0.471%）。

**episode 去重**：每檔股票施加 cooldown=max_horizon，同一波只取首次進場。

### up_only vs all 的差異解讀

`up_only` 是 `all` 的子集：SBL 減量 ≥10% **且** 當日個股收漲。  
這正是 live `tw_lending_monitor.py` 的「轉多訊號」分組規則——  
空頭縮手 + 股價已開始反彈 → 視為更強的轉多確認。

**回測驗證邏輯**：
- 若 `up_only` 在 H=5/10/20 的超額報酬 / edge 顯著高於 `all`，說明「加收漲條件」能過濾掉品質較差的事件，live 分組有統計依據。
- 若差異不顯著或方向反轉，應重新評估分組條件的有效性。

### Headline 數字（2025-01-01 起，首跑結果）

> `python3 tw_lending_backtest.py --json-out concept_momentum/cache/lending_backtest.json`（2026-07-06 完成，1895 檔 universe）

| 組別 | H=5 n/超額/CI | H=10 n/超額/CI | H=20 n/超額/CI |
|------|--------------|----------------|----------------|
| 撤退 all | 5122 / −0.36% / [−0.56,−0.17] | 4972 / −0.32% / [−0.61,−0.05] | 4794 / **−1.36%** / [−1.78,−0.92] |
| 撤退 up_only | 3119 / −0.27% / [−0.53,−0.0] | 3044 / **−0.05%** / [−0.44,0.33] | 2924 / −1.04% / [−1.62,−0.43] |
| 議借 low (<1%) | 4059 / −0.06% / [−0.26,0.15] | 3991 / −0.11% / [−0.40,0.18] | 3863 / −0.51% / [−0.98,−0.07] |
| 議借 high (>7%) | 1198 / **−0.95%** / [−1.40,−0.50] | 1148 / **−1.30%** / [−1.98,−0.59] | 1091 / **−2.06%** / [−3.09,−1.03] |

**★ 關鍵發現**：
1. **空頭撤退是熊市訊號，不是轉多訊號**：all 組在所有持有期超額報酬均顯著為負（CI 全負），H=20 超額 -1.36%。「SBL 減量」更多反映到期還券/制度性原因，非主動空頭平倉。
2. **up_only 比 all 稍好（H=10 差距最大）**：up_only H=10 超額 -0.05% (CI 含 0，不顯著)，而 all H=10 超額 -0.32% (CI 全負)。「收漲條件」確實過濾掉部分品質較差的事件，但兩組整體方向仍偏負。live 系統「收漲=轉多確認」在回測中**部分成立**（up_only 較不差），但**不等於正超額**。
3. **高費率議借 (>7%) 是強烈的空頭確認**：all horizons CI 全負，H=20 超額 -2.06%。空頭願付高價借股=對下跌有強烈信念；歷史驗證有效。
4. **低費率議借 (<1%) 接近中性**：H=5/10 CI 含 0，H=20 輕微偏負。非強訊號。

**樣本量 caveat**：
- 空頭撤退：all 5190 / up_only 3179（SBL 日減 -10% 全市場很常見）
- 議借 low_rate (<1%)：4201 筆（低費率議借比想像中多）
- 議借 high_rate (>7%)：1217 筆（費率 >7% 雖罕見，但全市場下仍有足夠樣本，無 n<30 問題）

### 限制

⚠ **議借 5 日均窗口語意與 live 不同**：回測用『該股自身有議借的最近 5 個交易日』做基準（需 ≥5 個歷史議借日，首度出現的『新出現』股不觸發）；live tw_lending_monitor 用全市場日曆窗、且無前期紀錄的股票會以 999% 直接觸發。因此回測事件集偏向『常有議借的股票』，新出現型訊號未被評估 — 兩者結論不能逐一對映。

1. **SBL 制度性還券雜訊**：到期強制還券、除權息前必還等制度性因素會觸發 SBL 大幅減少，但不代表空頭主動撤退（轉多）。未過濾此類事件，兩組均含結構性雜訊。
2. **樣本期間偏短**：面板 start=2025-01-01，約 1.5 年，多為多頭期；空頭環境下結論可能不同。
3. **議借利率帶方向不同**：low_rate 和 high_rate 對後續股價的含義截然相反，不可混讀。
4. **成本假設**：0.471% 假設零滑價；借券股流動性有時偏低，實際成本更高。

Dashboard 頁面：`/lending-backtest`（四組各一表，含 n<30 樣本不足警語）

---

## 回測共用工具

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

## 參數敏感度掃描 (`tw_param_sweep.py`)

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

## tw_chip_price.py — 單檔日內籌碼 × 價格 × 時間 三維分析 (CLI / Skill)

跟 `/chip` 不同 — `/chip-price` 專看單日 (broker × price × time) 三維分布，
偵測主力 footprint。Report 含 8 個 section：

1. **Header** — 代號 + 名稱 + 日期 + OHLC + 漲跌% + 總量
2. **🔥 Top 10 大單 cells** — 個別 (broker × price × side) 最大 10 筆，含 direction tag (⬇/⬆/↗/↘/△/▽)
3. **⏰ 三階段分析** — 早盤/盤中/尾盤各方主力 + 主賣方。**有 FinMind tick data 時用實際時間切分** (09:00-10:08 / 10:08-12:22 / 12:22-13:30)；無 tick 時 fallback 到價格 quartile heuristic
4. **🎯 Top 5 買超分點價格指紋** — 每分點 avg、範圍、**adaptive 主買集中區** (自動選最緊密 70%-30% threshold，cap 25% of day range)、Top 3 買價、**📈 主買區軌跡** (跨日 band 移動：推升中/下移/盤整)
5. **🎯 Top 5 賣超分點價格指紋** — 同上但賣方
6. **🌀 高賣低買 — 同分點兩面操作 (洗盤低接)** — 偵測同分點當日 sell_avg > buy_avg 模式 (wash_score)，**有 tick data 時加 buy_time/sell_time 時序分類**：✅ 真洗盤低接 (先賣後買) / ⚠ 追漲獲利出 (先買後賣) / ⏱ 時序模糊。**2026-05-15 補：每筆 wash 候選額外輸出主賣集中區 + 主買集中區 + Top 3 賣價 + Top 3 買價（與 Top 5 買超/賣超 section 對稱）**，方便對照同分點高賣 vs 低買的具體成交價分布。
7. **🧭 分點行為 — 近 N 日連續買賣序列** (2026-07-17 加) — 依券商名稱把今日重要分點（買賣超 Top 8 各方 + 所有達門檻的外資/散戶指標分點）分成 **🌏 外資 / 🏠 散戶指標 (永豐金、國泰敦南) / 🏦 內資買方/賣方** 四組，每個分點列出**近 10 日逐日淨買賣序列**：`07/15 +6.0k@83% | 07/16 -2.6k@48%`，`@%` = 當日買（賣）均價在該日高低區間的位階（0%=最低價、100%=最高價），另附今日淨額 + N 日累計。**刻意不做制式行為標籤** — 行為判讀（隔日沖慣犯 = 平日零活動→某日高位階大買→隔日全倒；真累積 = 逐日同向 + 累計墊高；沖來沖去 = 逐日劇烈翻面累計歸零）由分析者看序列敘事。資料來源：`bsr_cache/*_prices.json` 優先（有均價位階）、plain aggregate fallback（只有淨額）；**休市日 stale cache 自動剔除**（整日 (buy,sell) 簽名與前日完全重複即丟棄 — 2026-07-10 事件 215/215 檔重複 07/09 資料）。入選門檻 max(100 張, 當日總量 0.2%)。⚠ 外資分點含客戶委託、非全為外資自營；散戶指標為經驗 proxy；`—` = 該日無 cache 而非零買賣
8. **📅 連續性 (三層 view)** — (A) 今日 Top 3 買賣方在近 N 日 Top 3 命中次數；(B) **2026-05-15 加：近 N 日累積淨買/賣 Top 5**（不限今日 Top 3，捕捉「間歇式大量」主控分點；出現天數 ≤ 40% N 標記 ⚡ 間歇大量）；(C) **2026-05-15 加：今日 Top 3 之 N 日累積指紋**（顯示今日量 + 前 N 日累積 + 歷史最大日；若今日量 ≥ 60% 總量標記 burst）

### 核心分析 pattern (2026-05-13 完整版)

**A. 個別分點價帶集中度** (`broker_concentration_band`)
- Sliding-window 找該分點 ≥70% volume 的最窄連續價格區間
- Adaptive threshold：寬度 > 25% 全日 range 時降閾值，找出最緊密集中點
- 高 % + 窄區間 = surgical 操作（演算法/有目的的進場）
- 低 % + 寬區間 = 一般 averaging in（散戶 / 雜訊）

**B. 跨日主買區軌跡** (`broker_band_progression`)
- 讀 `chip_price_history/{code}_{date}.json` 取近 N 日該分點集中區
- 比較 band low 趨勢：upward = 推升、downward = 下移、unchanged = 盤整
- 推升中 = 主力連日加碼且接受更高成本
- 下移 = 平均成本下降，常見於 averaging-down 或 chase 反向動能

**C. 同分點兩面操作 / 高賣低買 + 低賣高買** (`broker_wash_candidates`, 2026-05-20 強化)
- `wash_score = (sell_avg - buy_avg) / day_range`
  - `> 0`: 高賣低買 (sell_avg > buy_avg) — 看似空但低接累積
  - `< 0`: 低賣高買 (sell_avg < buy_avg) — 認錯買回 / 慘賠加碼 (2026-05-20 加)
- **三層過濾防止 noise / lopsided 假 wash**：
  1. 兩邊都 ≥ 1 張 (1000股, 排除零股)
  2. 兩邊都 ≥ 1% × 當日總量 (排除單側 noise)
  3. min/max ratio ≥ 10% (排除 214買/1賣 這種一邊極小的偽 wash)
- **4 quadrant 時序判讀** (有 tick data 時):
  - 高賣低買 + 先賣後買 = ✅ 真洗盤低接 (bullish 主力低接)
  - 高賣低買 + 先買後賣 = ⚠ 追漲獲利出 (bearish 短線獲利)
  - 低賣高買 + 先賣後買 = ⚠ 認錯買回 (補回認賠或翻多)
  - 低賣高買 + 先買後賣 = ❌ 殺低出貨 (恐慌賣)
- 每筆 wash 候選額外輸出主賣集中區 + 主買集中區 + Top 3 賣價 + Top 3 買價

**D. 時序方向判定** (`build_price_to_time_map` + tick data)
- 用 FinMind `TaiwanStockPriceTick` (sponsor) 抓毫秒級 ticks
- 為每個價位算 volume-weighted avg time
- 對 wash 分點: buy_time - sell_time ≥ 30min → ✅ 真洗盤低接 / sell_time - buy_time ≥ 30min → ⚠ 追漲獲利出 / 否則 ⏱ 時序模糊

**E. 真實時間 三階段** (`time_stage_breakdown`)
- 用 price→time map 把每個 (broker, price, side) row bucket 到時間 quartile
- 前 25% / 中 50% / 後 25% session 時間 (09:00-10:08 / 10:08-12:22 / 12:22-13:30)
- 比舊版「價格 quartile 當時間 proxy」可信，能偵測**同分點日內方向反轉**
- e.g. 2313 5/13: 元大早盤 -5,251 → 尾盤 +439 (借勢洗盤)

**F. 連續性 footer** (`_format_continuity` + `_aggregate_broker_history`, 2026-05-15 重構)
- **Section A** 今日 Top 3 買賣方在近 N 日歷史 Top 3 命中次數
  - 高命中 = 持續主導 (信號可信)
  - 0/N = broker 完全輪替（短線投機 / pattern reversal）
  - 設計上 **excludes today**（hit rate 對照基準）
- **Section B** 近 N 日累積淨買/賣 Top 5（不限今日 Top 3）
  - 解決「間歇大量」盲點：broker 可能間隔幾天才買、但單日量很大也能主控走勢
  - 出現天數 ≤ 40% × N 標 ⚡ 間歇大量
  - 排序：純按 abs(total_net) 降序（規模優先）
  - **2026-05-15 改用 bsr_cache 全資料**（800+ 分點/日，非只 top 5），window 預設 5 日 = 1 trading week
  - Window 自動 include today (若今日 BSR 已公布)，視窗 label 顯示「近 5 日 (含今日 MM/DD)」或「近 N 日 (今日數據未公布)」
- **Section C** 今日 Top 3 之 N 日累積指紋
  - 每位今日 Top 3：顯示「今日量 + 前 N-1 日累積 = N 日累積 + 歷史最大日」
  - 若今日 |量| / N 日累積 ≥ 60% → 標 burst (今佔大半)
  - 區分「穩定大戶」(burst 0) vs 「今日 burst 進場」(burst 1)
  - 同樣讀 bsr_cache，能 catch chip_price_history top 5 漏掉的中量 broker
- **2026-05-19 加：1 月持有成本** (Section B + C)
  - 每行末加「(N日 均買成本 $XXX)」或「(N日 均賣價 $XXX)」
  - 從 bsr_cache `_prices.json` 算 volume-weighted avg price
  - 目標 20 trading days; 實際取在地可得天數 (透明標 "N日")
  - 主力 cost vs 現價 = 套牢 / 獲利狀態的快速判讀

**G. 分點 N 日時段 pattern** (`broker_timing_pattern`, 2026-05-20 加)
- 給定 (stock_code, broker_id, n_days=6) → 自動算每日該分點在「早盤 09:00-10:08 / 盤中 10:08-12:22 / 尾盤 12:22-13:30」三時段的買賣分布
- 配對當日 OHLC + 自動分類走勢「開高走低 / 開低走高 / 中性」
- 6 種行為標籤（依 dominant stage ≥50% + 淨方向）:
  - 🎯 尾盤低接型 (尾盤+淨買) — swing 部位
  - ⚠ 尾盤倒貨型 (尾盤+淨賣) — day-trade 結算
  - 🚀 早盤追擊型 (早盤+淨買) — 動能策略
  - 📉 早盤出貨型 (早盤+淨賣) — 停損 / 反向獲利
  - ⚖ 盤中布局/出貨型 (盤中) — TWAP/VWAP 演算法
  - 🔀 多時段混合操作 — 無明確 pattern
- 網頁版 broker drilldown 自動顯示, 每個標籤附可展開的詳細解讀 (專有名詞 + 推論依據 + 實務含意)

**G. 精準時序匹配 — 跨 cell 一致性** (`match_broker_cells_consistent`, 2026-05-14 加入)

舊的 `build_price_to_time_map` 只給「**該價位整體**」的成交平均時刻，跟「**該分點在該價位的成交**」可能差很多。實測 ground truth：第一員林 5/14 \$50.30 50 張實際 11:35:38 成交，舊算法估算 12:17 (差 42 分鐘)；\$50.40 30 張實際 11:36:12，估算 12:37 (差 61 分鐘)。

新算法 — 4 層 fallback：

1. **`build_tick_index(stock_code, date)`** — 從 FinMind 抓全部 ticks，建 `{price: [(time_min, vol_zhang), ...]}` index
2. **`_cell_candidates(cell_vol, tick_list)`** — 對每個 BSR cell，枚舉所有「leading_block」候選 tick：vol 至少佔 cell_vol 70%、嚴格小於 cell_vol (因為 BSR cell 通常是「主要 block + 小量 cleanup」組合，不是單一 tick 與 cell 完全相等)
3. **`match_broker_cells_consistent(cells, side, ticks_by_price)`** — 跨 cell 共聚 (cross-cell consistency)：
   - **Anchor**：某 cell 有「明顯獨大」的 candidate，視為 anchor (high confidence)
     - 單一 candidate
     - 或 top vol ≥ 1.3× second vol
     - 或同 vol 但 top cluster_span 寬 ≥ 5× → broker accumulation pattern
       (寬 cluster = 主 block + 鄰近 cleanup 小單，比 isolated single tick 更像同分點)
   - **Centroid**：所有 anchor 的 time 加權平均
   - **Pull**：模糊 cell (多候選 / 無明顯獨大) 取最接近 centroid 的 candidate
4. **Fallback** — 無 candidate 退到 `weighted` (price→time avg)

`match_type` 標籤透露信心度，UI 顯示為 confidence badge：
- ✅ `exact` — 單一 tick vol 完全等於 cell vol (僅小 cell)
- 🎯+ `leading_block_consistent` — leading block + cross-cell anchor 一致
- 🎯 `leading_block` — leading block 但無 anchor cross-check
- 🔄 `window` — sliding window 多 ticks 和等於 cell vol
- ≈ `weighted` — vol-weighted avg fallback

**8 個 ground truth case 驗證 (2026-05-14 ~ 2026-05-15)**：

| # | Stock | Cell | 用戶實際 | 演算法 | 狀態 |
|---|---|---|---|---|---|
| 1 | 3491 | 第一員林 \$50.30 52張 | 50張 block @ 11:35:38 + 2 cleanup | ~11:36 | ✅ |
| 2 | 3491 | 第一員林 \$50.40 34張 | 30張 block @ 11:36:12 + 4 cleanup | ~11:36 | ✅ |
| 3 | 3491 | 兆豐台南 \$50.60 37張 | 30張 main @ 10:32:50 + spread to 10:36 | ~10:33 | ✅ |
| 4 | 3491 | 兆豐台南 \$50.20  8張 | 4張 + 4×1張 burst @ 13:16:20-24 (4 sec) | ~11:58 (alt 13:14 ≈ truth) | ❌ |
| 5 | 2316 | 兆豐台南 \$137.50 17張 | 17張 全 in 集合競價 09:03:44.396 | ~09:03 | ✅ |
| 6 | 2316 | 兆豐台南 \$137.00 4張 | 4張 全 in 集合競價 09:03:44.396 | ~09:03 (primary) | ✅ |
| 7 | 2316 | 兆豐台南 \$136.00 15張 | 15張 集合競價 09:05:51.373 | ~09:02 (primary) | ⚠ 偏早 3 分 |
| 8 | 2316 | 兆豐台南 \$132.50 1張 | 1張 限價單 12:18:53.054 | ~10:47 ≈ | ❌ 差 91 分 |

**演算法原則 (從 case 1-3 推出)**：
- 真實 broker 主力 buy = lead block + cleanup small ticks 散布幾分鐘 (span 寬)
- 別人剛好同 vol 單一筆 = isolated single tick (span 窄)
- 當 2+ candidates 都 lead_pct >= 70% (都可疑)，**取 cluster_span_min DESC** 比 lead_vol DESC 準
- 例：兆豐台南 5/14 \$50.60 37 張 — 候選 35張@10:28 (span 3s = 別人) vs 30張@10:33 (span 4min = 用戶) → 取 span 寬 ✓

**Case 4 + 8 揭露的根本限制 — 三種 broker 填單 pattern**：

| Pattern | 結構 | Span | 識別性 |
|---|---|---|---|
| **A. 擴散填單** | lead block + cleanup 散在分鐘級 (case 1-3) | 寬 (10s-4min) | ✓ 用 span DESC 區分 |
| **B. 密集 burst** | lead block + cleanup 全在秒級 (case 4) | 窄 (3-10s) | ❌ 跟其他 broker 短 burst 無法區分 |
| **C. 集合競價** | 開盤前隊列 / 5-sec 撮合，所有單同一 ms 成交 (case 5-7) | 0 秒 | ✓ 一次大 tick anchor — 演算法表現完美 |

**Case 8 揭露 Pattern D — 「小張數 + 熱門價多 cluster」場景**：
- 1 張 限價單 @ \$132.50，但全日該價成交 121 ticks
- 121 ticks 分布在 09:07~09:09 (早盤殺低 65 ticks) + 12:18~12:44 (盤中 56 ticks) 兩個 cluster
- 演算法找不到 lead block (張數太小)，fallback 到 121 tick 加權平均 ~10:47
- 結果落在兩 cluster 中間「真空帶」，91 分鐘誤差，且無法靠 alternatives 修正（多 cluster 不在 alternatives 範圍）
- **本質**：1-3 張小單在 100+ tick 熱門價無法 anchor，公開資料無解

**同一個 broker 可能 cell A 用 Pattern A 填、cell B 用 Pattern B/D 填**（兆豐台南 5/14 \$50.60 用 A，\$50.20 用 B；5/15 \$137.5 用 C，\$132.5 用 D）。對 Pattern B/D 公開資料無解 — TWSE 沒提供 broker→tick mapping。

**對使用者的影響 / 補償**：
- 工具自動產生 `alternatives` (top 2 不同時間 candidates) 顯示在 UI
- Case 4 例: primary ~11:58 ❌，alt ~13:14 ✓ (跟 truth 13:16 只差 2 分)
- Case 8 例: primary ~10:47 ≈ — 多 cluster 場景已加上「multi_cluster」標記 + 各 cluster 時段顯示，使用者可從自己 trade 記憶選對 cluster
- 使用者用 alternatives + 自己 trade 記憶可以**手動修正** algorithm 的猜測

### 滾動歷史 archive (chip_price_history)

- 每次 `analyze()` 自動寫 `chip_price_history/{code}_{date}.json` (slim ~50-200 KB)
- Rolling 10 個交易日，自動 prune
- broker_monitor 18:00 cron 已加入 chip_price_history backfill — 每天**融資餘額 top 200** 檔自動累積
- **`chip_cache_builder.py`（20:30 cron，2026-07-21 加）** — broker_monitor 的 top-200 融資選股會漏掉低融資的族群/強勢股，本器補一份**動態 union**：族群成分股（concepts.json themes 全成員 ~194）∪ 強勢股候選（近 5 日 second_wave_history）∪ 推播 watchlist ∪ 當日成交金額熱門 top-N（排除 ETF）。**跳過當日已快取的**（不重抓 broker_monitor 已抓的）→ 只補缺口（實測 ~140 檔）。排 20:30 避開 18:00 broker_monitor 長工（最長 105 分），並內建 `pgrep tw_broker_monitor` 等待守門（TPEx Playwright 共用 Xvfb :99 不能並行）。用法 `--list-only`（只印清單）/`--hot-n N`（熱門股數，0=不加）/`--max N`（union 上限防爆時間）。目的：讓族群資金流/強勢股/熱門股每天有分點資料持續累積

### 使用
```bash
FINMIND_TOKEN=... python3 tw_chip_price.py 2313
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --telegram   # 推 TG
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --json-out out.json
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --date 20260512 --no-fetch  # cache only
```

### Skill 觸發
- `/chip-price 2313`
- "2313 籌碼價格" / "2313 分點價格" / "2313 籌碼量價"

### 自動 cron (固定觀察名單)

`tw_chip_price_daily.sh` — 每天 08:50 跑 3491/2313/6282 (sequential，因 3491 是 TPEx Playwright)

### Telegram 推送紀律

**完整 7 段缺一不可** — 禁止為節省篇幅省略任何 section。`_send_telegram` 自動 chunk >4000 字元訊息。
參見 `~/.claude/skills/chip-price/SKILL.md` 顯式紀律。

### 限制與 caveat
- **TWSE (上市)** 100% 支援；**TPEx (上櫃)** 透過 Playwright + Turnstile (~30 sec/檔，3491 已驗)
- **tick data 估算時序是 proxy**：weighted-avg 算法易被尾盤大量成交拉偏；G 段的精準匹配對「主 block + cleanup」cell 有效，但對全分散小單 (e.g., 全部 1-3 張零散買) 退回 weighted (`match_type=weighted`)
- **chip_price_history 需累積** — broker_monitor 18:00 cron 開始累積 (2026-05-13 上線)，**第 2 天起**有跨日軌跡，第 3+ 天起資料完整
- CAPTCHA 解析靠 ddddocr，成功率 ~80% (失敗自動重試 10 次)
- 主買區軌跡需 ≥ 1 日歷史；連續性 footer 需 ≥ 1 日歷史
- FinMind tick data 需 sponsor 版 (有 token 即可)；失敗時自動 fallback 到 price-quartile 三階段 + net-based wash 判讀
- **單一價位多 broker 同 vol coincidence** 在 G 段 cross-cell consistency 解之前是無解的：若該分點全部 cell 都缺乏 anchor (同 vol 多 candidates 而 cluster span 差不多)，centroid 無從建立 → 退回最大 vol candidate 當代表 (可能誤判)。這是公開資料 (BSR 沒分點 → tick mapping) 的根本上限
- **Pattern B 密集 burst 填單無解** (case 4: 兆豐台南 \$50.20 8張 4 秒內 4+1+1+1+1) — broker 用市價/積極限價單秒級填單，跟其他 broker 的短 burst 無法區分。Mitigation: 工具自動顯示 alternatives 讓使用者用自己 trade 記憶手動 override。詳見上面 4 case 表

## 訊號成效追蹤 (`concept_momentum/run_outcomes.py`)

**自動後照鏡**：把 5 個推播策略每天存的 history JSON，自動配上 FinMind 還原價計算 T+1/5/10/20 的實際報酬 vs 大盤超額，每週一 08:10 推 Telegram 週報。

### date 正規化表（各策略 entry 口徑）

| 策略 dir | date 欄語意 | 進場日 (entry_date) 規則 |
|----------|------------|--------------------------|
| `turnaround_relay_history` | **資料日**（盤前資料，date = 前一交易日） | date 之後的**下一個**交易日（隔日開盤） |
| `second_wave_history` | **執行日**（盤前 07:40，date = 當日） | ≥ date 的**第一個**交易日（當日開盤） |
| `broker_radar_history` | 資料日（盤後 18:00） | date 之後的下一個交易日 |
| `lending_radar_history` | 資料日（盤後 16:00） | date 之後的下一個交易日 |
| `short_retreat_history` | 資料日（盤後 21:30） | date 之後的下一個交易日 |

### entry 口徑

- **進場價**：entry_date 的**還原開盤價**（TaiwanStockPriceAdj，開盤買最保守可實現口徑）
- **出場**：`trading_dates[entry_idx + h - 1]` 的還原收盤。h=1 = 進場當日開→收，h=5 ≈ 1 週

### T+h 慣例

```
h=1  : 進場日開盤 → 進場日收盤（持有當天）
h=5  : 進場日開盤 → 進場後第 5 個交易日收盤（~1 週）
h=10 : ~2 週
h=20 : ~1 個月
```

成效 = `(T+h 還原收 / entry 還原開 − 1) × 100 − TAIEX 同窗報酬`

### 產出

- `concept_momentum/cache/signal_outcomes.json`：全訊號報酬記錄 + 5 策略彙總 + TR abcd 分桶 + SW score 三分位 + **SW 分層標記分桶 (`sw_tier_buckets`，2026-07-08 加入)** + **SW 借券急跌標記分桶 (`sw_sbl_buckets`，2026-07-09 加入)**
- `concept_momentum/cache/outcomes_px/`：TAIEX + 個股還原價 快取（1 天 TTL）
- Dashboard：`/signal-outcomes` 獨立頁面（含 glossary，含 SW 分層標記分桶表 + SW 借券急跌標記分桶表）

**SW 分層標記分桶 (`sw_tier_buckets`)**：second_wave 訊號按 `tw_second_wave.py` 寫入的 `tier` 欄位（⭐/◐/▽）分桶，缺欄位（2026-07-08 前的舊訊號）歸入 `untagged` 桶，各桶算 h=1/5/10/20 的 n/exc_mean/win — 用來 forward-test 「子群分析」節的分層結論是否在新訊號上繼續成立。TG 週報僅當 ⭐ 或 ◐ 桶 T+5 樣本數 ≥5 才顯示分層行，避免初期噪音誤導。

**SW 借券急跌標記分桶 (`sw_sbl_buckets`)**：second_wave 訊號按 `tw_second_wave.py` 寫入的 `sbl_tag` 欄位（借↓/借↑/—）分桶，缺欄位（2026-07-09 前的舊訊號）歸入 `untagged` 桶，各桶算 h=1/5/10/20 的 n/exc_mean/win — 用來 forward-test 「籌碼確認（借券急跌變化）」節的結論是否在新訊號上繼續成立。TG 週報暫不加此桶（桶尚空，待累積樣本）。

### Cron

```
10 8 * * 1   # 每週一 08:10（交易日） → 計算 + TG 週報
```

### 使用

```bash
# 手動跑（不推 TG）
FINMIND_TOKEN=... python3 concept_momentum/run_outcomes.py

# 手動跑 + 推 TG
TG_BOT_TOKEN=... FINMIND_TOKEN=... python3 concept_momentum/run_outcomes.py --telegram
```

### 配額保護（FinMind）

- 空回應不寫 cache
- 每次 API 呼叫 sleep 0.03s
- 個股失敗 → skip + n_px_failed 計數
- >50% 個股失敗 → `[ABORT]` + sys.exit(3)

### 已知限制

- 回測窗口從 2026-04-01 起算（各 history dir 的最早落地日），樣本僅 ~60 天
- lending_radar 日均 50+ 檔訊號，個別 n 很大但訊號稀釋度也高
- 還原價使用 TaiwanStockPriceAdj，除權息前後日的跳空已消除，但盤中操作無法還原
- 今日訊號（entry_date = today）T+h 出場尚未發生，不計入統計

---

### 未來改進 (TODO / wishlist)

1. **分點行為 profile 跨檔聚合** — 同一 broker_id (e.g., 1480 高盛) 在 N 檔股票橫向看其行為一致性，建立 `broker_profile/{broker_id}.json` 持久檔案。可知該分點主要型態：定點主力 vs 散戶 vs algo vs 市場做市。當前每日分析孤立，不利累積長期 broker 知識。

2. **G 段時序匹配的 self-correction** — 提供使用者「**自助校準介面**」(web UI add-on)：使用者輸入自己實際 trade 時間 → 工具存進 `chip_price_truth/{date}/{broker}/{price}.json` → 隔日演算法在計算 anchor 時把這些 known-truth point 當高權重 anchor。
   現況：使用者只能口頭告訴我演算法錯了 → 我手動 reverse engineer 一次。理想：使用者點頁面輸入 → 工具下次自動更準。

3. **Tick-level broker assignment via 多日累積 pattern** — 同一個 broker 通常有特定下單規模 + 時段偏好。多日 ticks 累積後，可以 cluster：哪些 ticks 屬於同一個 trader/algo？這需要 unsupervised learning (clustering on volume, time-of-day, follow-up pattern) — 大工程，但能突破 BSR 無 timestamps 的根本限制。

4. **分點協同買進偵測 (broker chain coordination)** — 第一銀證在 6282 5/14 有 22 個分點同向買入 (合計 +180 張)，typical 主力借小分點群分散下單。可建立檢測：當同 broker prefix (e.g., 538*=第一銀，9800*=元大) 在同一檔多個分點同向總計超過閾值 → flag 為 coordinated。**已在 C 方案 D 點 backlog，今天還沒做**。

5. **TPEx tick data 支援** — 目前 `TaiwanStockPriceTick` FinMind sponsor 含 TPEx (3491 等)，需驗證 ticks 結構是否一樣，並調整 build_tick_index 處理上櫃格式差異 (如果有)。

6. **三階段分析跟 G 段 match_type 統一基底** — 三階段目前用 `price→time` weighted avg 來分配 row 到時段，跟新的 leading_block 邏輯不一致 (price→time 在 leading_block 看來會被拉偏)。應該讓三階段也用 G 段同樣的演算法，per-cell 確定時間後才 bucket。

7. **wash candidates 信心度標籤** — 現在只判 ✅ 真洗盤 / ⚠ 追漲後出 / ⏱ 時序模糊，沒給 confidence。可加入：buy_match_type 跟 sell_match_type 兩邊都 `leading_block_consistent` → 高信心；任一邊 `weighted` → 中信心。

8. **可指定多檔對照** — `/chip-price 2313+6282+3491` 同時查多檔，網頁顯示對比表 (e.g., 三檔的 高盛 today net 對比)。對「外資 同日反向 across 多檔」這種訊號有用。

9. **歷史 tick data 持久化** — FinMind sponsor 每次抓 tick 都拉一次 (~3 秒)。可以在 18:00 cron backfill 時也 cache `tick_cache/{code}_{date}.json`，讓 web UI 查歷史日子瞬間返回 (現在歷史日 backfill 沒 cache tick)。

10. **TLDR / executive summary section** — 報告 7 段內容資訊密度高，第一眼難消化。可加 section 0：「3 行判讀」(主力方向 / 量能信號 / wash 訊號)，給快速 decision-maker 用。剩 7 段詳細為 drill-down。

---

## 策略改進 Backlog（需獨立 plan，本計畫不做）

1. **盤中模擬 (intraday-sim) 的處置**：回測已證明無方向 skill（skill_vs_zero -2.4%，方向命中 51.6% vs 「永遠猜跌」57%）且信心帶過窄（41% vs 目標 50%）。選項：(a) `/intraday-sim` 頁面頂部加紅字告示「回測顯示無方向預測力，僅供情境想像」；(b) 加寬帶寬重新校準；(c) 下架。至少做 (a)。
2. **主力雷達訊號設計**：Pearson corr 算在 n=5 天上幾乎無過濾力（`tw_broker_lookup.py:212`）。bsr_cache 已累積 40+ 天 → 可改 `--days 10`。注意：改參數後 `broker_radar_history` 新舊事件不可混合回測，需重新累積 1-2 個月再評估。改前先用現行回測基準線存檔。
3. **參數敏感度掃描**：對第二波 7 條件、TR 6 參數做 grid 掃描 + walk-forward（2025 調參 / 2026 驗證）。必須在 Task 3/10 之後做（有了可信的衡量才有調參的意義）。
4. **倖存者偏差**：universe 改用含下市股的清單（FinMind `TaiwanStockInfo` 含 `date` 欄位可判斷；或 TWSE 下市公司名單），回測面板補抓已下市股票價格。
5. **美台聯動多重比較**：`--scan` 對 ~190 檔挑最高相關 = winner's curse。輸出加 split-half 驗證欄（前半窗 vs 後半窗 corr 同號才標「穩定」）。
6. **turnaround screener 資料源**：Yahoo → FinMind（其他工具 2026-05-11 已遷移，`tw_turnaround_screener.py:40` 還在用 Yahoo，rate-limit 靜默跳過會讓 universe 每天不同）。同時加「抓取失敗計數」到輸出——區分「無候選」與「資料斷線」。
7. **組合層模擬**：事件研究之上加簡單組合模擬（同時最多 K 檔、等權、資金重複使用規則），回答「這些策略疊起來的資金曲線長怎樣」。
8. **沉睡巨人 / 美台聯動 回測**：沉睡巨人持有期長（月~年），需要不同的評估框架（6m/12m horizon + 觸發稀少）；美台聯動是配對訊號非選股訊號。各開獨立 plan。
9. **dormant_giants 還原價來源**：Yahoo adjclose → FinMind `TaiwanStockPriceAdj`（sponsor 已可用，README 註記過時）。

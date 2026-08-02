---
name: reference-site-nav
description: site_nav.py 全站共用 UI — 統一導航/表格自動排序/sticky/拖拉/深色模式/favicon/public_url;新頁面必掛 nav_html()
metadata: 
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

`site_nav.py`(repo root,2026-07-31 加)— tw_stock_tools 網站共用 UI 模組:

## 新頁面上線 checklist(重要)
1. render_html 開頭用 `nav = __import__("site_nav").nav_html("/新route")` — **不要再手寫 <nav>**。
2. 把 `("/新route", "emoji 名稱")` 加進 `NAV_LINKS`(一處改、全站同步)。
3. **首頁 tab 入口必加**(用戶 2026-08-01 明確要求「以後不要忘了」)——`concept_momentum/templates/dashboard.html` **和** `concept_momentum/concept_charts.py` **兩處同步**加 `<a class="tab" href="/新route" ...>emoji 名稱</a>`(concept_charts 是 17:00 cron 重生成 dashboard.html 的來源,只改一處會被蓋掉)。foreign-cost 就是漏了這步被抓。
3. 掛了 nav_html 自動獲得:統一導航(當前頁粗體)、頁寬 1100、**th sticky**、**所有表格自動可點排序**(data-v 優先;若頁面自帶排序,th 有 onclick 即整表跳過)、過寬容器自動拖拉橫滑(.adrag;自帶 .dragx 跳過)、**深色模式**、favicon 📈、**個股 K 線彈窗**(/kline.js:點「4碼代號+名稱」格 → 日K+MA5/20/60+VOL+MACD;資料 /api/kline/<code> 當日快取;regex 排除日期/價格誤觸)。
4. 推播訊息的連結用 `site_nav.public_url("/route")`(ngrok 靜態域名 shudder-attention-musky.ngrok-free.dev,env PUBLIC_BASE_URL 可覆蓋)——**別寫 localhost**(手機點不開)。

## 深色終端機主題(2026-07-31)
_SITE_CSS 即全站深色主題(不再是 media query,永遠深色):CSS vars --bg #0d1117/--card #151b23/--acc #4cc2ff/--up #ff6b6b/--dn #34c98e(dataviz 驗證過對比;紅綠 CVD 靠 +/−▲▼ 第二編碼)。sticky 玻璃 nav、th sticky top=--navh(JS 量測)、狀態徽章深色版、section[style*=fff8e1] 黃條轉深琥珀。首頁另有同色票深色塊插在 concept_charts.py(f-string {{}})+dashboard.html;Plotly 圖表刻意保留白底圓角卡。新頁沿用共同 class(section/.note/.up/.dn/.small)即自動好看。

## 機制
- nav_html() 注入 `_CSS + _SITE_CSS + <nav> + _ENHANCE_JS` 於 <body> 內 → 晚於各頁 head style,同權重下勝出(不用 !important)。
- 深色模式 `prefers-color-scheme: dark` 覆蓋共同 class(body/section/th/td/.note/.small/nav);熱力圖與徽章 inline 色刻意不動。
- 自動排序 cellVal:data-v 屬性優先 → 日期字串(YYYY-MM-DD)→ 數字(− U+2212 正規化、去逗號%x)→ 字串。
- concept_charts.py 是 **f-string 模板**:插 JS/CSS 大括號必須 `{{ }}` 跳脫(2026-07-31 踩過,SyntaxError)。dashboard.html(Jinja)單括號沒事。
- app.py 內頁模板也是 f-string:嵌 nav 用 `{__import__("site_nav").nav_html("/x")}`。
- headless browse 測試:每次 CLI 呼叫間 tab 可能掉回 about:blank → **goto+eval 要用一個 chain**;js 參數含 `!` 會被 bash history expansion 咬,複雜 JS 一律寫檔用 eval。
- **sticky th 陷阱(2026-07-31 踩過)**:`position:sticky` 的 top 相對**最近的捲動容器**,不是視窗——表格在 max-height 捲動 div 裡時 top 必須 0,設 nav 高度會讓表頭浮在表格中間(用戶手機截圖抓到)。boot() 已逐表判斷:有 overflow 祖先→top:0,否則 var(--navh)。手機(≤640px)nav.site 為 static(折三行太佔螢幕)。驗證 sticky 要量 **th 格** 的 rect,不是 thead row(row 不動、格才黏)。
- **表頭固定完整解(2026-08-01)**:表格在 overflow-x:auto section 裡 sticky 根本不會生效(section 是捲動容器但不垂直捲)→ boot() 把 ≥12 列大表**自動包進 80vh 捲動盒**(margin-scan 模式)。兩個 sticky 殺手:① `table.market-breadth{overflow:hidden}`(圓角)→ table 自成裁切容器 th 永不黏,要 overflow:visible !important ② 首頁 th 被高權重規則蓋成 relative(tooltip)→ 首頁 snippet 用 sticky !important。首頁不吃 site_nav 注入,同機制 snippet 手動放兩模板。headless 載不動首頁=plotly CDN 無外網,非站點問題。

## 已上線頁(22=全站):14 主工具頁 + 8 子頁(concept/second-wave/turnaround/lending/intraday-sim/broker-radar-backtest、margin-lookup、chip-compare,2026-08-01 補掛,nav_html(None)+保留子頁互連)。首頁自有 tab 系統+獨立深色塊(concept_charts.py 生成,注意 .chart-wrap/table 白底要覆蓋)。子頁淺色卡已有 .card/.v/.k/.warn/.error 覆蓋;.pos/.neg 用 filter 提亮不改色相(各頁紅綠語意不同)
相關:[[reference-ftd]]、[[reference-margin-scan]]

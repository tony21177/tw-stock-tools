# 💼 基本面工具:合約負債 / 存貨 / 存貨拆分 / 前十大股東

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

**合約負債歷史** — 單檔近 N 年每季合約負債 + QoQ/YoY/CAGR（CLI + 網頁；FinMind 缺資料時 fallback MOPS 季報 PDF 附註，2026-05-20 加 fallback）→ `tw_contract_liabilities.py` · `mops_pdf.py` · `/contract-liabilities?pdf=1`

**存貨歷史 + 衍生指標** — 單檔近 N 年每季存貨 + 週轉率/DSI/存貨營收比 + 圖表（CLI + 網頁，2026-05-15 加）→ `tw_inventory.py` · `/inventory`

**存貨 5 項拆分** — 從 MOPS 財報 PDF 解析原料/在製品/半成品/製成品/副產品/物料拆分，疊圖顯示（2026-05-17 加；2026-05-22 加平行下載 + ProcessPool 解析 20 季 80s→30s、網頁拆分回看年數下拉、解讀邏輯 YoY 為主 + QoQ 連 2 季同向加倍強化 ⚡ + 營收交叉警訊「存貨雙升 vs 營收沒跟上 → 庫存壓力劇增 🔴」、拆分表多 4 欄存貨總額 / 季營收 / 存貨銷售比 / DSI 天 色碼，存銷比 + DSI 互相驗證跨季節更穩定）→ `mops_pdf.py` · `/inventory?breakdown=1`

**前十大股東 + 集保大戶分布** — 輸入股號查 (a) MOPS 年報前十大股東（姓名 + 持有股數 + 持股比例 + 停止過戶日 + **關係人備註**；候選頁逐一解析容錯各家 layout、F04「主要股東名單」乾淨排名表為主、F17 前十大股東相互間關係表 fallback、按持股比率排序、<5 筆視為失敗、JSON+負快取）。關係人欄列出年報揭露的前十大股東相互間配偶/二親等/法人關係（如 2313 吳家三代、2408 台塑集團交叉持股、法人股東代表人/董事長）；可載入 **N 年（3/5/8/10）變化矩陣**（股東 × 年度持股% + ▲▼ 趨勢 + ★新進/已退榜，跨年用 F17 標準表 + 名稱正規化合併同一實體）；(b) 集保 TDCC 每週股權分散表，4 群組摘要（散戶/中實戶/大戶/千張大戶）+ 籌碼集中度趨勢線 + 級距長條圖 + 各群組週變化表（%/張數/人數）（2026-05-28 加）→ `fetch_major_shareholders()` in `mops_pdf.py` · `fetch_holding_distribution()` in `finmind_client.py` · `/shareholders?code=X`

---
name: 大盤寬度看板 (Market Breadth)
description: concept_momentum dashboard 最上方新分頁，13 欄 × 60 天的大盤+市場寬度數據表，含 ^TWII / >NMA% / 200新高 / 三大法人(4欄) / 融資餘額+增減
type: reference
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
dashboard.html 最上方第一個分頁「📊 大盤寬度」於 2026-05-10 加入，每日 17:00 cron 自動更新。

**13 欄定義**:
1. 日期、2. 加權指數、3. 漲跌幅%
4-6. 股價>20MA% / >50MA% / >200MA%
7. 200日新高數 (收盤價)
8-11. 外資 / 投信 / 自營 / 法人合計 (億)
12-13. 融資 (億) / 融資增減 (億)

**寬度池**: 上市+上櫃 普通股 4 位代號 (~2,300 檔)，排除 ETF/REITs/權證。

**檔案**:
- 計算: `concept_momentum/market_breadth.py`
- 渲染: `concept_momentum/market_breadth_renderer.py`
- 注入點: `concept_momentum/concept_charts.py:generate_html()` 的 `breadth_table_html` 參數

**Cache** (gitignored):
- `concept_momentum/cache/market_universe/{YYYYMMDD}.json` — 全市場當日收盤 (~118 KB/天)
- `concept_momentum/cache/market_breadth/{YYYYMMDD}.json` — 計算結果 (1 行 = 1 天)

**資料來源**:
- 全市場價格: FinMind `TaiwanStockPrice` (sponsor tier 必要)
- 三大法人: FinMind `TaiwanStockTotalInstitutionalInvestors`
- 融資餘額: FinMind `TaiwanStockTotalMarginPurchaseShortSale`
- 加權指數: Yahoo `^TWII` (已有 cache)

**設計文件**: `docs/superpowers/specs/2026-05-10-market-breadth-dashboard-design.md`
**實作計畫**: `docs/superpowers/plans/2026-05-10-market-breadth-dashboard.md`

**判讀提示**:
- >20MA% < 30 = 過度悲觀（可能反彈）
- >20MA% > 80 = 過度樂觀（可能修正）
- 200新高數 < 20 + 法人合計 連續負 = 弱市
- 融資增減連 5 日正 + >50MA% < 50 = 散戶逆勢加碼，警戒

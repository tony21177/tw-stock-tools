---
name: feedback_finmind_not_equal_financial_report
description: 斷言某股「財報沒有某科目」前，要翻 MOPS 真實財報 PDF，不能只看 FinMind
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---

要說某股票「財報沒有 X 科目」(合約負債、合約資產、預收款、某附註細項…)之前，**必須下載 MOPS 真實財報 PDF 全文搜尋確認**，不能只憑 FinMind 結構化資料就下結論。

**Why:** FinMind 的 `TaiwanStockBalanceSheet` 是 XBRL 彙總，只收「拆成獨立科目」的項目。財報附註裡有、但沒拆成獨立 XBRL 科目的東西，FinMind 就抓不到 → **「FinMind 沒有」≠「財報沒有」**。直接拿 FinMind 的缺漏當「公司沒這科目」是未經查證的斷言（違反 [[feedback_evidence_based]]）。

**範例教訓 (2026-06-17, 2408 南亞科)：** 使用者問為何抓不到合約負債。我第一次只查 FinMind(無 Contract 科目)就答「沒有」。使用者追問「你有檢查財報嗎」→ 我才下載 2408 2026Q1 合併財報 PDF(41 頁)全文搜尋：合約負債 0 次、預收 0 次、其他流動負債 578,636 仟元(附註六(十四))。結論這次才有真實財報背書。

**How to apply:** 用 `mops_pdf.download_pdf(code, roc_year, season)`(mtype=A/dtype=AI1 合併財報) + pdfplumber 全文搜尋關鍵字。民國年 = 西元−1911；季別 1-4。`fetch_contract_liabilities_series()` 若短路在 FinMind 回空，要改走 PDF parser 親自確認。相關工具見 [[reference_tw_stock_tools]]。

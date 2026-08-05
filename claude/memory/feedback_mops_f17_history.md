---
name: feedback-mops-f17-history
description: MOPS F17 前十大股東 N 年矩陣的缺年處理教訓 — 年報次年出/掃描圖檔/失敗勿快取空
metadata:
  node_type: memory
  type: feedback
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

前十大股東 N 年變化(mops_pdf.fetch_shareholders_history)三個坑(2026-08-05 騰雲 6870 案例):

**Why**:用戶查 5 年只出 1 年,原因被靜默吞掉 — ①end_roc_year 預設抓到「今年」但年報次年才出(115 年度年報 2027 年才有,白抓)②下載失敗被永久快取成空 list,之後永不重試 ③新上市公司(騰雲 113 年度才有首本年報)與「年報 F17 是掃描圖檔」(騰雲 114 年度,pdfplumber chars<200+images≥1)看起來一樣都是空。

**How to apply**:
- 抓年報系列預設 end = 民國(今年-1)年度;判掃描圖檔用 chars<200 且 images≥1
- 失敗分三類:查無檔(不快取,可重試)/掃描圖檔(快取 {"_status":"scanned"} 永久)/解析失敗(不快取)
- 缺年一律回傳 missing {yr: reason} 顯示於頁面 — 靜默吞年份會被用戶抓到(「不是5年?為什麼只有113年」)
- 舊快取的空 list 視為污染,讀到即重試

相關:[[reference-finmind-migration]]、[[feedback-evidence-based]]

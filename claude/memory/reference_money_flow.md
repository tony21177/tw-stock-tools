---
name: reference-money-flow
description: 族群資金流功能 — 34 主題板塊每日法人淨流+成交額占比輪動+四象限標記；2026-07-14 上線
metadata: 
  node_type: memory
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

族群資金流入流出功能（2026-07-14 加入 concept_momentum）：

- **模組**：`concept_money_flow.py`（抓取+計算+日檔+CLI）、`concept_money_flow_renderer.py`（純渲染）；日檔 `cache/money_flow/{yyyymmdd}.json`
- **指標**：成交值占比 vs 20 日均（pp，**精確**，來自 FinMind 真實 Trading_money）；法人淨流 = 淨股數×收盤價（**近似輔助**）；四象限標記 🔥真流入/⚠出貨疑慮/🧲低調吸收/❄退潮，門檻 `FLOW_SHARE_PP=0.15`pp + `FLOW_INST_NTD=0.5`億 + `FLOW_NET_GROSS_RATIO=10%`（淨流須≥總流量一成；2026-07-15 加入，擋外資投信對沖日雜訊 — 07-14 被動元件 +66.6 vs −66.8 淨 +2.77 億誤標 🔥 的教訓）（**先驗設定、未經回測** — 累積數據後可回測校準）
- **主排序 = 成交值占比 vs 20日均降冪**（2026-07-20 改；業界 XQ/MoneyDJ/CMoney「類股資金流」公認口徑 = 成交值佔比−20日均，精確非近似）；法人淨流金額降為輔助欄。TG 摘要「資金匯入/流出 Top5」也依占比排、法人淨流括號輔助。研究依據：XQ 細產業資金流向 `value1=GetField("資金流向");value3=value1-average(value1,20)`。占比 None（樣本不足）者排最後、以法人淨流為次鍵。改版價值實例：被動元件 占比-3.10pp 排流出榜首但法人+25億(🧲) — 舊法人金額排序會漏掉的熱度退潮+法人低接背離
- **判讀紀律**：🔥 在大跌爆量日也會出現（外資接刀/回補），≠ 看多；標記只看當日資金、不看價格方向，必須搭配走勢
- **外資買賣超區**（2026-07-15 加入同頁）：上市/上櫃**官方公布值**（上市 FinMind TaiwanStockTotalInstitutionalInvestors、上櫃櫃買中心 open data `tpex.org.tw/www/zh-tw/insti/summary?date=YYYY/MM/DD&type=Daily&response=json`）+ 當日個股買/賣超 Top15（近似值、排除 ETF）。缺官方時近似回填加 ~ 標示。口徑教訓：近似加總必須含 ETF（07-15 外資買 ETF +91.6 億，只算個股差官方 ~55 億）。schema 升級用 `--backfill N --force` enrich 舊日檔
- **入口**：dashboard「訊號監控」tab（17:00 烤入）+ `/money-flow` 獨立頁（即時）+ 動能排行表兩欄 + 每日 TG 摘要（只推當日資料存在的日子）
- **回補**：`python3 concept_money_flow.py --backfill 60`（resumable、需 FINMIND_TOKEN、FinMind 單日全市場 2 次呼叫）
- **主力個股 drivers**（2026-08-03 加入）：`aggregate_day` 每族群留 |法人淨額| 前 4 名且 ≥1 億個股，存日檔 `drivers` 欄 `[{c,n,i(億)}]`；TG 摘要匯入/流出 Top5 附 `↳` 子行、出貨疑慮附賣壓前 3；頁面族群名下小字 span（`data-kx` 可點 K 線彈窗，pos紅/neg綠）。舊日檔無此欄 → 顯示容錯略過；可 `--backfill N --force` enrich
- 注意：一檔可屬多主題 → 占比加總 >100%；權值股爆量會讓所屬主題占比同時失真
- 設計/計畫文件：`docs/superpowers/specs/2026-07-14-concept-money-flow-design.md`、`docs/superpowers/plans/2026-07-14-concept-money-flow.md`

相關：[[reference-market-breadth-dashboard]]、[[reference-all-strategies]]、[[feedback-dashboard-glossary]]

---
name: reference-vcp-screen
description: VCP 波動收縮掃描 /vcp — Minervini 型態(遞減收縮+量縮+pivot);趨勢模板前置;突破日推播;21:00 cron;未回測
metadata:
  type: reference
---

VCP 波動收縮掃描(2026-08-02,`tw_vcp_screen.py` · `/vcp`):

## 偵測口徑(調研自各家 scanner 共識)
- 前置趨勢模板:價>MA50>MA150>MA200(MA200 走揚>20日前)+ 距一年高<25% + 距一年低>+30% + 年RS≥70(IBD 加權,重用 tw_utility_screen._rs_score)。
- VCP:近130日 zigzag(5%)→ 回檔深度 2~6 段遞減(≤前段×0.85)、首段≤30%、低點墊高、近10日振幅≤8%、量縮 vol5<vol50×0.65。
- 形成中=距 pivot(近15日高)≤6%+量乾涸;突破=收盤>昨日前 pivot 且量≥1.5×vol50 → 推 TG(vcp_pushed.json 去重)。
- 🛡 標記=同在 utility_screen 名單(修正期抗跌+VCP=最強組合)。卡片牆+mini K 線(重用 /api/kline+_warm_kline)。
- **已回測(2026-08-02,tw_vcp_backtest)**:一年僅 **8 次事件**、失敗率 50%、H20 超額 −5.2% / H60 −17.5%,而**趨勢模板對照為正**(+1.8%/+2.7%)→ 台股機械式追 VCP 突破無證據有效。事件幾乎全是**低波動金融股假突破**(緊縮≤8%+量縮天然抓牛皮金融股)。與林則行箱型同教訓:**台股型態突破追價一再驗證無效**。定位=觀察清單;推播文已改強烈不建議追價。⚠ n=8 統計不可靠=「無證據有效」非「證明無效」。價量快取已回補至 2024-07(506 交易日)供後續回測複用。

## 首掃(2026-08-02,大盤剛崩 −9.7%)
母體 2,406 → 突破 0、形成中 1(環泰 4207:9.9→6.5→5.1%、乾涸 0.43)——崩盤週基底盡毀屬正常,盤穩後名單自然增,勿因當下名單少調鬆參數。

## Minervini 流程三件套
Utility Screen(修正期找抗跌股)→ VCP(型態成形/突破)→ FTD(大盤轉折定時機)。VCP 頁 glossary 已寫「大盤修正未止時突破失敗率高」。

## 上線
route /vcp + NAV_LINKS(🌀 VCP)+ 首頁 tab 兩模板 ✓;**21:00 cron**(20:50 utility 先跑完,重合標記才新鮮);★/K線彈窗/深色 自動 ✓。
相關:[[reference-utility-screen]]、[[reference-ftd]]、[[reference-lin-matrix]](箱型負回測前車之鑑)

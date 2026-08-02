---
name: reference-utility-screen
description: Utility Screen 抗跌領頭羊 /utility-screen — Minervini 修正期區間RS(距高點天數為視窗);啟動=加權距200日高>20日;20:50 cron
metadata:
  type: reference
---

Utility Screen 抗跌領頭羊(2026-08-02,`tw_utility_screen.py` · `/utility-screen`,用戶提供 Minervini 文章):

## 機制
- **啟動**:加權距「200日內最高收盤」>20 交易日 → utility mode,**視窗 N=距高點天數**(逐日+1)重算區間 RS;大盤創高或 N>200 → 退回標準年 RS(N=250)。`market_state()` 判定。
- **區間 RS**:IBD 加權式 score=2×r(最近N/4)+r+r+r(四段、最近段雙倍)→ 全市場百分位 1-99。
- **濾網**(文章口徑,不看一年低點):RS>85、股價>MA200、MA50>MA200、日均成交額>1億(近20日 vol×收盤估)、距自身200日高<25%。
- 資料全走現有快取(year_prices 還原價/vol_day/TAIEX FinMind);母體 ~2,338 檔。

## 首掃(2026-08-02,N=28、修正−9.7%)
47 檔:金融防禦(兆豐金/華南金/合庫金/上海商銀 貼高點)+軍工(漢翔+25%)+主題強勢(仁新+71%、華上生醫+68%)——修正期抗跌教科書組合。

## 用法敘事(頁面已寫)
觀察清單非進場訊號:修正期掛名單看 VCP/量縮不跌(供給枯竭),等 **FTD(/ftd)** 大盤轉折時,名單中最先突破樞紐買點者=風報比最佳。與 FTD 工具是設計上的搭檔(Minervini 原文即配 Follow-Through Day)。

## 呈現(2026-08-02 v2,用戶要求照原作者截圖)
卡片牆:統計列(符合數/距高點天數/最高RS/平均RS)+ 每檔 mini K 線卡(canvas 近120根蠟燭+MA20/60+量柱,fetch /api/kline 併發5、build 時 _warm_kline 預熱)+ RS/距高點/成交額徽章;點卡片開大圖(kline.js `[data-kx]` 委派);表格收摺疊。

## 上線
route+NAV_LINKS(🛡 抗跌領頭羊)+首頁 tab 兩模板 ✓(checklist 全做);**20:50 cron**(extremes 20:00 先建 year_prices);不推播;未回測(頁面揭露);★ 標記 ✓;K線彈窗自動 ✓。
相關:[[reference-ftd]](搭檔)、[[reference-site-nav]]

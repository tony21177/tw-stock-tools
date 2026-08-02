---
name: reference-market-overnight
description: 明天大盤預期 /market-tomorrow — 隔夜美股(SOX/Nasdaq/ADR)→ 隔天加權指數方向;回測跳空81%/收-收72%
metadata:
  node_type: reference
  type: reference
  originSessionId: 32952c56-c95d-4931-8a29-3c139f09d137
---

明天大盤預期(2026-07-25 加,`tw_market_overnight.py` · `/market-tomorrow`):

## 緣起(重要脈絡)
盤中走勢模擬 `tw_intraday_sim`(相似日類比法)回測發現:**對「個股隔天方向」≈銅板(51%)、skill 為負、信心帶嚴重過度自信(25-75%帶只覆蓋 32-41%,該50%)**。用戶問怎麼改善 → 驗證「隔夜美股→隔天台股」相關性極強 → 做成獨立大盤預測工具。

## 方法
- 特徵:^SOX 費半 / ^IXIC 那指 / ^GSPC 標普 / TSM 台積ADR 隔夜報酬(Yahoo,cache/overnight_us.json)+ **台指期夜盤報酬**(FinMind TaiwanFuturesDaily,cache/tx_night.json)。用戶要求「考慮新聞/事件」→ 夜盤 = 隔夜新聞聚合器(15:00→05:00 含美股收盤後+亞洲+台灣本地)。
- ⚠⚠ **夜盤日期慣例大坑**:FinMind `after_market` session 掛在「結束日 D」(跑 D-1傍晚→D清晨)。夜盤報酬**必須** = 夜盤收(D)/前一交易日日盤收(D-1) −1、**同一口契約**、對齊**當日(D)開盤**。誤用「夜盤收(D)/日盤收(D)」(把清晨值除以同日下午值)→ corr≈0 看似無訊號(debug 兩小時的教訓;用原始值印 日盤收/夜盤開 才發現夜盤開≈前一日日盤收)。跨契約月(結算換月)價差數千點也會污染 → 要同契約。
- 模型:滾動 OLS(前 WINDOW=120 日)→ 收-收 與 開盤跳空。信心帶=訓練殘差經驗分位數(校準)。
- 特徵動態:predict_next 若目標日夜盤已更新(最新夜盤日>最新現貨日)用 5 特徵,否則退回美股 4 項;build_dataset(raw, night) night=None 走美股。輸出含**%與點數**(點數=%/100×最新加權收盤 ref_level)。

## 回測結論(walk-forward)
- **美股+夜盤 開盤跳空:方向 87.0%(高信心 97.6%)、skill +19%**
- **收-收:方向 76.8%、skill +26%**
- 夜盤增量:單美股 84%→加夜盤 87%(夜盤單獨也 85%,比美股準)。夜盤未更新自動退回美股仍 ~84%。
- 三病全治(對比舊盤中模擬):方向 51%→76-87%、skill 負→正、信心帶校準(舊 32-41% 過度自信)。

## 關鍵教訓:只能預測大盤,個股救不了
驗證 beta×市場預期對**個股**方向:base 44% → 命中僅 **52.3%**;就算隔夜大波動(>1.2%)也只 54.9%。**個股每日漲跌以自身雜訊(±3-5%)為主,市場成分(±1%)蓋不過**。故工具刻意只做指數,個股頁面標「背景風向」。純方向 sign 比對(SOX漲→台股漲)零參數即 70%,樣本外有效。

## 上線
- 網頁 `/market-tomorrow`(app.py route,含回測成效表)+ 首頁「即時工具」nav(concept_charts.py + dashboard.html)。
- 測試 tests/test_market_overnight.py(合成資料,不連網)4 項。
- **每交易日 07:30 cron 推睏霸數錢(C96e49)+田尾三人幫(Ca0735)**(盤前、美股收盤後;`--line-to a,b` 逗號分隔,推播時強制抓最新隔夜 max_age_h=0)+存 cache/market_overnight_history/。cron 閘 is_trading_day.py(需 FINMIND_TOKEN);工具本身只用 Yahoo 不需 FinMind。

相關:[[reference-lin-matrix]](同樣「回測誠實揭露無/有edge」)、[[reference-strategy-history-tabs]]

# 📐 期現貨基差 / 外資期貨留倉監控

| | |
|---|---|
| 頁面 | `/futures-basis` |
| 模組 | `tw_futures_basis.py` + `index_dividend_points.py` |
| 排程 | 盤中 9-13 時每 5 分 + 17:30 告警 + 17:35 富台 OI 自動記錄 |
| 上線 | 2026-07(多次改版) |

## 核心觀念

- **外資期貨留倉淨額 98% 是期現套利對沖腳,無方向意義**(顯示但標 caveat)
- **基差必用除息調整後**:加權是價格指數,除權息旺季(6-9月)數百點「結構性逆價差」
  純屬待除息、非看空。調整後基差 = 原始基差 + 結算前剩餘除息點數 D
  (D 精算:前 50 大權值股 TaiwanStockDividend,覆蓋 ~75-85%,頁面標覆蓋率)

## 監控訊號

①逆價差腳/basis_extreme/directional_warn(全用調整後基差)
②三訊號同步「跌+逆價差+台幣貶」 ③基差-留倉套利一致性 ④月底轉倉
⑤特定法人近月 vs 遠月(TAIFEX 大額交易人) ⑥富台(SGX TWN)OI
(TradingView scanner 端點自動抓,`twn_oi_manual.json` 累積)。

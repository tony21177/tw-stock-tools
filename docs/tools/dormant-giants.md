# 沉睡巨人(tw_dormant_giants)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 12. `tw_dormant_giants.py` — 沉睡巨人篩選器

### 用途
找出「曾經 5 倍股、跌幅 ≥30%、沉睡 ≥5 年、近期長時間量縮窄幅整理」的標的。
這類股票的特徵：
- 過去有故事、有資金推升過 → 證明商品/題材有想像空間
- 但現在已被市場徹底遺忘，籌碼洗淨、套牢盤消化
- 波動率被壓到底、量也縮到底 → 沒人關心
- 若有新催化事件 (產業景氣回暖、新題材、業務轉型)，向上爆發力大且阻力小

### 五項過濾 (各須滿足)
| 條件 | 預設 | 意義 |
|------|------|------|
| **A 曾 5 倍股** | peak/peak前低點 ≥ 5x | 還原收盤峰值除以峰前低點，且峰前需有 ≥3 年資料才算數 (避開 Yahoo 起點即峰值的假訊號) |
| **B 跌 ≥ 30%** | current ≤ 70% × peak | 從峰值修正 |
| **C 峰值 ≥ 5 年前** | peak_date ≤ today − 5y | 退潮已久 |
| **D 近 5 年無炒作** | 5y max/min < 3x，任 120td 滑窗 max/min < 1.5x | 確認沒被再炒過 |
| **E 量縮震盪** | 60d 振幅 < 10%，60d 量 ≤ 75% × 3y 平均量 | 真正的窄幅整理 |

預設由原 10x / 跌 50% 放寬到 5x / 跌 30%（實證 10x+50% 全市場僅 0-2 檔太嚴；5x+30% 約 5 檔較合理）。
若想看更嚴格名單可加 `--min-peak 10 --max-current-pct 0.5`。

### 資料源
| 資料 | 來源 |
|------|------|
| 還原股價 | Yahoo Finance `adjclose` (含 split + dividend；多數 case 也涵蓋減資)。FinMind `TaiwanStockPriceAdj` 需付費，本工具用 Yahoo 替代 |
| Universe | FinMind `TaiwanStockInfo` (與 turnaround_screener 共享 universe_all 快取，4 位數普通股) |

注意：Yahoo TW 資料起點 ~2007，2007 前已達峰的個股 (e.g. 6244 茂迪 2006 高點 >900) 可能漏抓。
透過 `--min-pre-peak-years` (預設 3) 強制要求峰前 3 年資料，自動排除這類「資料截斷」假訊號。

### 使用方式
```bash
# 預設掃全市場
python3 ~/project/tw_stock_tools/tw_dormant_giants.py

# 推送 Telegram
TG_BOT_TOKEN=xxx FINMIND_TOKEN=yyy \
  python3 ~/project/tw_stock_tools/tw_dormant_giants.py --telegram

# 放寬倍數 (預設 10x 太嚴可改 5x)
python3 ~/project/tw_stock_tools/tw_dormant_giants.py --min-peak 5

# 放寬量縮條件
python3 ~/project/tw_stock_tools/tw_dormant_giants.py \
  --max-60d-range 0.15 --vol-decline-ratio 1.0
```

### 性能
全市場 ~3000 檔，cold cache (Yahoo 抓 18 年) ~5-10 分鐘 (6 workers 平行)；
warm cache 後續查詢 < 1 分鐘 (cache 7 天)。

### 排序邏輯
按 `沉睡年數 × (0.20 − 60d 振幅) × (0.40 − 量比) × 倍數/10` 由大到小排序，
即「越久沉睡 + 越窄整理 + 越大歷史倍數」越優先。

### 實例（2026-05-03 全市場掃描，預設 5x / 跌 ≥30%）
篩選漏斗：2,141 → A:1,327 → AB:757 → ABC:220 → ABCD:19 → **ABCDE:5 檔**

| 代號 | 名稱 | 倍數 | 跌幅 | 沉睡 | 60d 振幅 | 60d/3y 量比 |
|------|------|------|------|------|---------|------------|
| 9944 | 新麗 | 6.6x | 72% | 11.8y | 8.3% | **0.30x** |
| 2496 | 卓越 | 14.9x | 60% | 9.0y | **5.5%** | 0.58x |
| 6195 | 詩肯 | **31.9x** | 52% | **12.4y** | 8.5% | 0.73x |
| 1474 | 弘裕 | 9.9x | 45% | 5.9y | 6.4% | 0.60x |
| 5487 | 通泰 | 26.4x | 38% | 6.6y | 9.6% | 0.71x |

亮點：
- **9944 新麗** 量縮 + 跌幅 + 沉睡三項皆領先，綜合品質最高
- **2496 卓越** 60d 振幅 5.5%，五檔中波動最緊
- **6195 詩肯** 31.9x 倍數最高、沉睡 12.4 年最久
- **5487 通泰** 26.4x 高倍數、2019 後一路冷卻

### 限制
- Yahoo 資料對減資 (capital reduction) 的還原可能不完美 — 邊角案例需手動驗證
- 「沉睡」≠「會漲」— 工具只是過濾「有可能 turnaround 的池子」，不是買入訊號
- ABCDE 五關全過的標的數量稀少 (台股全市場每天大約 0-5 檔)，建議搭配基本面研究

---

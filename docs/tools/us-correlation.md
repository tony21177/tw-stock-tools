# 美台聯動(tw_us_correlation)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 7. `tw_us_correlation.py` — 美台聯動 (US-TW Beta)

策略名：**美台聯動** (CLI) — β 調整後 TW 個股 vs US peer 相關性，扣除大盤 β 後仍同步的真聯動

### 用途
找出台股哪些標的真的跟著指定美股 peer 動。可指定一個概念內掃描，或直接對全市場（34 個概念去重共 ~190 檔）跑相關性。

典型用途：
- 「想做 NVDA / BE / AMD 行情但只能買台股 → 找最高相關度的影子股」
- 「驗證某概念是不是真的跟著 narrative 美股動」（e.g., 台股 ASIC 跟 AVGO 連不連動？）
- 「同一家公司 ADR vs 母股，相關性能多高？」（TSM vs 2330 = +0.47，揭示日線級別 ADR 連動上限）

### 資料來源
Yahoo Finance（query1.finance.yahoo.com）— 同 `concept_momentum/data_fetcher.py`，台股自動加 `.TW` / `.TWO` 後綴，美股直接用 ticker。資料範圍依 window 自動切換：window ≤ 100 用 `6mo`，101–200 用 `1y`，> 200 用 `2y`。

### 計算邏輯（β 調整版，預設）
1. 抓近 6 個月或 1 年日線
2. 算每日 daily return: `(close_t - close_{t-1}) / close_{t-1}`
3. **β 調整**：
   - 台股 vs `^TWII`（台灣加權）算 β（線性迴歸斜率：`Cov(s,m)/Var(m)`）
   - 美股 vs `^GSPC`（S&P 500）算 β
   - excess_return = stock_return - β × market_return
   - 目的：去除「全球 risk-on 共漲」的雜訊，留下真正的個股 idiosyncratic 連動
4. **時差對齊**：TPE D ↔ US D-1（TPE D 反應的是前一晚 US 收盤，US D 的 session 在 TPE D 之後才發生）
5. Pearson 相關係數於指定視窗（預設 240 個 TPE 交易日，約 1 年；可用 `--window 60` 看近期 narrative）

### 兩種模式
| 模式 | 用途 | 數值範圍 | 風險 |
|------|------|---------|------|
| **β 調整（預設）** | 找真正 idiosyncratic 連動 | 通常較低（0.2–0.5） | 數字小看似不顯著 |
| `--raw` | 直觀「美股漲台股也漲」 | 通常較高（0.4–0.7） | 含全球 β，可能誤判共漲為連動 |

實例：1605 華新 vs AMD
- raw：+0.35（看起來中等相關）
- β 調整：+0.19（揭示其實沒實質連動，只是兩邊各自吃了 AI risk-on）

### 使用方式
```bash
# 單一概念查詢（預設用該概念內建美股 peer）
python3 ~/project/tw_stock_tools/tw_us_correlation.py ASIC自研晶片

# 指定特定 peer
python3 ~/project/tw_stock_tools/tw_us_correlation.py ASIC自研晶片 --peer MRVL

# 全市場掃描（推薦）— 不漏掉跨概念的高相關股；預設 240 天視窗
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer NVDA

# 看近期 narrative（60 天視窗）
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer BE --window 60

# 跑 raw 看共動，含全球 β（小心雜訊）
python3 ~/project/tw_stock_tools/tw_us_correlation.py --peer BE --raw

# 列出所有概念與預設 peer mapping
python3 ~/project/tw_stock_tools/tw_us_correlation.py --list
```

### 預設美股 peer mapping
腳本內 `US_PEERS` dict 涵蓋全部 34 個概念，例如：
- ASIC自研晶片 → AVGO, MRVL, ALAB
- AI伺服器_ODM → DELL, HPE, SMCI
- AI伺服器_電源 → VRT, ETN, GEV
- NVIDIA供應鏈 → NVDA
- HBM記憶體 → MU
- CPO_矽光子 → ANET, CIEN, COHR
- 半導體設備 → AMAT, LRCX, KLAC, ASML
- SiC功率元件 → ON, WOLF
- 重電_電網 → ETN, GEV, HUBB

每季可依市場焦點微調此 dict。

### 解讀門檻
| 範圍 | 圖示 | 意義 |
|------|------|------|
| ≥ 0.6 | 🟢 強相關 | 直接 narrative driver，幾乎可當 proxy 交易 |
| 0.3–0.6 | 🟡 中等 | 有 narrative 連動，可作為 hedge 候選 |
| < 0.3 | ⚪ 弱 | 自己走自己的，台美連動弱 |

注意：β 調整版數字普遍較低 — `β-adj 0.3 ≈ raw 0.5` 的訊號強度。

### 已知限制
- 日線資料的時差對齊已盡量處理（TPE D ↔ US D-1），但仍有 ADR 溢價、隔夜 gap、匯率影響
- `--raw` 模式的高相關常常是「共同蹭 macro narrative」，要用 β 調整版驗證
- ADR 同公司（TSM vs 2330）的相關性上限約 +0.47（時段錯開、資訊分裂）— 不要期待 1.0
- 視窗選擇影響大：60 天反映近期 narrative，180/240 天反映中長期；兩者差距大代表近期有 regime change（如台船 60 天 +0.46 vs 240 天 +0.14，60 天為短期巧合）
- 預設 240 天是為了過濾掉短期雜訊，得到較穩定的相關性畫面；要看近期變化用 `--window 60`

---

# 美台聯動(tw_us_correlation)

> 本文件自 README 拆出(2026-08-02 文件重整)。索引見 [README](../../README.md)。

## 7. `tw_us_correlation.py` — 美台聯動 (US-TW Beta)

策略名：**美台聯動** (CLI + 網頁 `/us-correlation`，2026-08-03 加網頁入口) — β 調整後 TW 個股 vs US peer 相關性，扣除大盤 β 後仍同步的真聯動

### 網頁版 `/us-correlation`
- 美股代號輸入(逗號分隔最多 4 檔)+ 概念下拉(留空 = 全市場掃描)+ 視窗 240/120/60 + 原始報酬勾選
- 概念模式即時算(數十秒);全市場掃描背景執行緒跑(2-5 分鐘),結果快取 `concept_momentum/cache/us_corr/{peers}_w{window}.json` 當日有效,頁面每 20 秒自動刷新直到完成
- 代號可點 K 線彈窗、有股期標★、術語表在頁尾

### 用途
找出台股哪些標的真的跟著指定美股 peer 動。可指定一個概念內掃描，或直接對全市場（34 個概念去重共 ~190 檔）跑相關性。

典型用途：
- 「想做 NVDA / BE / AMD 行情但只能買台股 → 找最高相關度的影子股」
- 「驗證某概念是不是真的跟著 narrative 美股動」（e.g., 台股 ASIC 跟 AVGO 連不連動？）
- 「同一家公司 ADR vs 母股，相關性能多高？」（TSM vs 2330 raw = +0.51,揭示日線級別 ADR 連動上限）

### 資料來源
Yahoo Finance（query1.finance.yahoo.com）— 同 `concept_momentum/data_fetcher.py`，台股自動加 `.TW` / `.TWO` 後綴，美股直接用 ticker。資料範圍依 window 自動切換：window ≤ 100 用 `6mo`，101–200 用 `1y`，> 200 用 `2y`。

### 計算邏輯(v2,2026-08-04 全面改版)

> v1 → v2 改版原因:未還原價的除息假報酬、Pearson 被單日極端值綁架、β 視窗與相關視窗錯配、
> 美股只扣 S&P 殘差仍含科技 sector 共同因子、排行榜無顯著性資訊(190 檔取 max 有 winner's curse)。

**Step 1 — 還原價報酬**
Yahoo `adjclose`(除權息還原)算日報酬,缺 adjclose 時 fallback 收盤。
未還原價在除息日會出現 −3~−5% 的假下跌(台股殖利率 3-5%),
既稀釋真相關、又可能與美股某天共現造出假相關。

**Step 2 — 缺值防護**
相鄰兩筆收盤相隔 >5 個日曆日(停牌/長假)時,該筆跨日報酬捨棄,
避免「多日累積報酬」對到大盤「單日報酬」。

**Step 3 — β 調整(同視窗估計)**
- 台股:excess = r − β·^TWII,β 用「相關視窗內」的日期交集估(OLS Cov/Var),
  不用全抓取範圍 — 2 年前的 β regime 不該影響近 240 日的判斷。
  (上櫃股理想上該用櫃買指數,但 Yahoo `^TWOII` 資料落後數週不可用,故一律 ^TWII。)
- 美股:**雙因子** excess = r − b1·SPX − b2·NDXresid,其中
  NDXresid = ^NDX 對 ^GSPC 迴歸後的殘差(Gram-Schmidt 正交化的科技因子)。
  只扣 S&P 時,mega-cap 科技股彼此的殘差仍共享 tech sector 行情,會高估個股連動;
  正交化後兩因子不共線,非科技股 b2≈0 自動退化為單因子。^NDX 抓不到時 fallback 單因子。

**Step 4 — 時差配對**
TPE 第 D 天配「嚴格小於 D 的最近美股交易日」(binary search)。
台股白天開盤反應的是美股前一晚收盤;台股週一配美股週五;美股假日時兩個台股日共用同一美股日。

**Step 5 — Winsorize + Pearson**
配對後兩序列各自截尾在 mean±3σ 再算 Pearson。
財報日 ±15%(META 級)或台股漲跌停共現一天,就能把 240 日的 r 撐高 0.1-0.2 — 截尾後
「單日巧合貢獻的相關」大幅壓低,留下的才是日常同步性。

**Step 6 — 顯著性與穩定性**
- `n`:有效配對天數(240 視窗實際 ≈ 230,扣首日/缺值/配對損耗)
- `95% CI`:Fisher z 變換信賴區間 tanh(atanh(r) ± 1.96/√(n−3))。**CI 含 0 = 不顯著**;
  60 日視窗 r<0.3 基本站不住。
- `前/後半`:視窗切兩半各算一次 r,|差| > 0.20 或正負相反標 **⚠** —
  整段相關可能只由某半段短期巧合貢獻(實例:台船 60 日 +0.46 vs 240 日 +0.14)。
  穩定的真聯動應前後半相近。
- 190 檔取 max 排序天然有 selection bias(winner's curse),榜首請看 CI 與 ⚠ 再信。

**基準驗證**(v2 上線時):TSM↔2330 raw +0.51(CI +0.41~+0.60,前/後半 +0.47/+0.53 穩定)
— 同公司 ADR 是日線相關的實務上限,其他配對高於此值即可疑。

### 兩種模式
| 模式 | 用途 | 數值範圍 | 風險 |
|------|------|---------|------|
| **β 調整(預設)** | 找真正 idiosyncratic 連動 | 通常較低(0.1-0.4) | 數字小看似不顯著 |
| `--raw` | 直觀「美股漲台股也漲」 | 通常較高(0.3-0.6) | 含全球/科技 β,共漲誤判為連動 |

實例(v2):2330 vs TSM — raw +0.51,β 調整 +0.26(雙因子吸掉科技共漲後剩的真連動)。

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
- ADR 同公司（TSM vs 2330）的 raw 相關上限約 +0.51（時段錯開、資訊分裂）— 不要期待 1.0
- 視窗選擇影響大：60 天反映近期 narrative，180/240 天反映中長期；兩者差距大代表近期有 regime change（如台船 60 天 +0.46 vs 240 天 +0.14，60 天為短期巧合）
- 預設 240 天是為了過濾掉短期雜訊，得到較穩定的相關性畫面；要看近期變化用 `--window 60`

---

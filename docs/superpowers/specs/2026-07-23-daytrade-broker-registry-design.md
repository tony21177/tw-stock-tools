# 隔日沖分點標記層 — 設計文件

**日期**：2026-07-23
**狀態**：設計已核准，待實作

## 一句話

維護一個「隔日沖/短線大戶分點」註冊表，來源 = 靜態種子 + 多來源網路交叉比對 + 我們累積 BSR 資料的行為偵測；在籌碼敘事裡對這些分點打 `⚡隔日沖` 額外標籤，避免把它們的買盤誤讀成內資機構認同。

## 緣起

`classify_broker_type` 只分 外資/內資(本土券商)/散戶指標。使用者指出：永豐金匯立(9A81)= 本土永豐金證券 → 歸「內資」正確，但「內資」是本土券商大雜燴，把機構/大戶/隔日沖混在一起。而 web 查證顯示公認隔日沖分點是凱基松山、美林、摩根大通、國票敦北等（永豐金匯立其實不在標準名單）。需要獨立的隔日沖標記層。

## 核心決策（已核准）

1. **資料驅動偵測**：符合隔日沖型態就**自動加入**，標 `data 來源 + 分數`、可回溯。
2. **標記方式**：**額外標籤**，不改 外資/內資/散戶 三分法（外資的美林/摩通也可同時是隔日沖）。
3. **網路更新**：**多來源交叉比對**，≥2 來源才算「網路確認」，不靠單一來源。

## 元件

### 註冊表 `concept_momentum/cache/daytrade_brokers.json`

```json
{
  "updated": "2026-07-23",
  "brokers": {
    "凱基-松山": {"sources": ["seed","web","data"], "web_count": 3,
                  "data_score": 0.42, "confidence": "confirmed",
                  "codes": ["9268"], "first_seen": "...", "last_updated": "..."},
    "永豐金匯立": {"sources": ["data"], "web_count": 0, "data_score": 0.31,
                   "confidence": "candidate", "codes": ["9A81"], ...}
  }
}
```

- `confidence`：`confirmed`（web≥2 來源 OR data_score ≥ 高門檻）/ `candidate`（單 web 來源 OR data 中門檻）。
- 比對用「分點名稱正規化」（去空白）+ 代號雙軌（名稱有別名時靠代號）。

### `daytrade_brokers.py`（新模組，repo root）

- **靜態種子** `_SEED`：公認名單（凱基松山/城中/信義、美林、摩根大通、國票敦北、富國建邦、元大土城永寧、統一士林、群益金鼎大安、中信忠孝…；web 驗證來源記在註解）。
- `update_from_web(dry_run=False) -> dict`：派 headless Claude（`claude -p --dangerously-skip-permissions`）搜多個台股財經來源（股感、玩股網、CMoney、豐雲學堂、財經部落格），萃取各家隔日沖分點名單，**交叉比對出現來源數**，回結構化 JSON。≥2 來源 → confirmed。prompt 明文要求「至少查 3 個獨立來源、列出每個分點出現在哪些來源」。
- `update_from_data(bsr_dir, days=50, ...) -> dict`：掃 bsr_cache `*_prices.json`，對每個分點算隔日沖分數：跨所有 (股票, 連續兩交易日) 配對，計「日N 大買（淨買 ≥ 該股當日量 X%）→ 日N+1 大賣（把日N 買的倒掉 ≥ Y%）」的 cycle 數；分數 = cycle 數 / 該分點活躍天數（正規化）。高分（≥ 高門檻）自動加、標 data。門檻先驗未回測、可調。
- `merge_registry(seed, web, data) -> registry`：三來源併，算 sources/web_count/data_score/confidence，寫檔（原子）。
- `load_registry()` / `is_daytrade(name_or_code) -> bool` / `daytrade_info(name_or_code) -> dict|None`：供敘事層查詢。

### 整合 `tw_chip_price.py`

- 分點行為序列每筆加 `daytrade`（bool）+ `daytrade_conf`（confirmed/candidate/None），用 `daytrade_brokers.is_daytrade(name/code)`。
- `_format_behavior` / renderer：對命中者顯示 `⚡隔日沖`（confirmed）/`⚡隔日沖?`（candidate）。

### 整合敘事 prompt（`concept_momentum/chip_narrative.py`）

- 完整版/快速版 prompt 附上「本檔今日出現的已知隔日沖分點：<清單>」，要求 AI 對這些分點的買盤不得解讀為「內資機構認同」，須標短線性質。

### 排程

- **每週日 cron**（`is_trading_day` 不擋週末 → 用純日期）：
  - web 更新（Claude 搜尋，~5-10 分）
  - data 更新（掃 bsr_cache，~1-2 分）
  - 各自 merge 進註冊表、更新 `last_updated`；過時（近窗不再符合）的 data-only 條目降 confidence。

## 風險與 caveat

- **web 萃取靠 Claude**：不同來源用詞不一（凱基松山 vs 凱基-松山 vs 凱基證券松山），需正規化；prompt 要求回代號優先。單來源可能是舊聞 → 靠 ≥2 交叉比對過濾。
- **data 偵測門檻先驗未回測**：隔日沖定義（大買%、隔日倒掉%）是啟發式；分數與門檻可調，敘事對 candidate 標「?」不強斷。
- **外資分點也可能是隔日沖**（美林、摩通）→ 標籤獨立於身分，兩者並存。
- **名單會變**：券商大戶會換分點；靠週更 web + data 保持新鮮，過時降信心。
- **不是買賣訊號**：標記只描述分點慣性，不預測漲跌。

## 測試

- 種子/正規化/is_daytrade 查詢（名稱與代號雙軌）。
- data 偵測：小樣本 fixture（造一個「大買→隔日大賣」分點 vs 一個波段分點），驗分數與門檻。
- merge：三來源併、confidence 分級、原子寫。
- web 更新：mock headless Claude 回傳 JSON，驗解析 + 交叉比對計數。
- 整合：行為序列項帶 daytrade 旗標、renderer 顯示標籤。
- 全部 offline（mock claude/檔案）。

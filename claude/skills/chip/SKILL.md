---
name: chip
description: 台股單檔籌碼總覽 — 借券 + 分點 + 融資三線整合分析。當使用者說 "/chip XXXX"、"XXXX 籌碼狀況"、"XXXX 三線"、"XXXX 籌碼總覽"、或同時要看借券+分點+融資時觸發。
---

# Chip — 台股單檔籌碼總覽

## 觸發時機

- 使用者明確要 `/chip <code>` 或「<code> 籌碼總覽 / 三線 / 整合」
- 使用者連續問了多個籌碼維度（借券 → 又問分點 → 又問融資）暗示要整合 → 主動建議跑 chip
- 使用者只問單一維度（如 "借券還券"）**不要**自動升級成 chip — 用 lending_lookup 即可

## 執行流程

### Step 1 — 借券（lending_lookup）

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tw_lending_lookup.py <code>
```

抓今日 + 昨日的 借券交易、還券明細、借券賣出餘額。

**對近 2 週軌跡**也要跑（建議用 awk 一次抓完，速度快）：

```bash
cd ~/project/tw_stock_tools && for d in $(交易日列表); do
  /usr/bin/python3 tw_lending_lookup.py <code> --date $d 2>&1 | awk '
    /━━━ 今日/ { date=$3; in_today=1; borrow="0"; rtn="0"; bal="待"; chg=""; sb=""; sr=""; next }
    /━━━ 昨日/ { in_today=0 }
    in_today && /借券交易:/ { getline; if ($0 ~ /合計:/) {gsub(/合計: /, ""); gsub(/張.*/, ""); borrow=$0} }
    in_today && /還券明細:/ { getline; if ($0 ~ /合計:/) {gsub(/合計: /, ""); gsub(/張.*/, ""); rtn=$0} }
    in_today && /當日賣出:/ { sb=$2 }
    in_today && /當日還券:/ { sr=$2 }
    in_today && /當日餘額:/ { bal=$2 }
    in_today && /餘額變化:/ { chg=$2 }
    /━━━ 昨日/ && in_today==0 { printf "%s 借%s 還%s | 賣出%s 還券%s 餘額%s (%s)\n", date, borrow, rtn, sb, sr, bal, chg; exit }
  '
done
```

### Step 2 — 分點（broker_lookup）

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=<從 crontab 抓> \
  /usr/bin/python3 tw_broker_lookup.py <code> --days 7 --top-n 15
```

如果結果為空（沒分點符合「≥3 天買超 + 融資正相關」），直接讀 BSR cache 列今日 Top 10 賣超 + Top 10 買超分點：

```python
import json
with open(f'/home/kun/project/tw_stock_tools/bsr_cache/<code>_<today>.json') as f:
    data = json.load(f)
items = [(b, info['name'], info['buy'], info['sell'], info['buy']-info['sell'])
         for b, info in data['brokers'].items()]
items.sort(key=lambda x: x[4])  # ascending = sellers first
# top 10 賣超 = items[:10], top 10 買超 = items[-10:][::-1]
```

### Step 3 — 融資（margin_lookup）

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=<token> \
  /usr/bin/python3 tw_margin_lookup.py <code>
```

抓融資餘額、近 N 日變化、維持率 cohort。

### Step 4 — 族群熱力交叉（可選，加分項）

讀最新 concept_momentum 結果看這檔屬於什麼族群：

```bash
ls -t ~/project/tw_stock_tools/concept_momentum/cache/results/analysis_*.json | head -1
# 然後 grep 該檔代號出現在哪個 theme
```

## 輸出格式（Telegram 友善）

```
<code> <name> 籌碼總覽（<date> 即時）

現價 $<price> <±%>

【今日 (YYYY-MM-DD) 即時】
🔵 借券：新借 X張 / 還券 Y張 / 餘額變化 Z%
🟢 分點：Top 3 賣超 [...] / Top 3 買超 [...]
🟡 融資：今日餘額 N / 變化 ±M張

【近 2 週軌跡】
（借券 + 分點 + 融資 三線並列日線）

【三線整合判讀】
1. 借券面：（依紀律解讀）
2. 現股面：（外資 vs 散戶分點誰主導）
3. 融資面：（散戶是否逆勢加碼）
→ 綜合：（多/空/觀望）

【關鍵價位】
- 上方壓力：<從近期高點>
- 下方支撐：<從近期低點 / MA / 前波啟動點>
```

## 判讀紀律 — 必遵守

### ⚠️ 紀律 1：「借券交易」≠「借券賣出」
- `t13sa710` (借券交易) 是借入券的事件，借出後**未必拿去做空**
- `TWT93U` (借券賣出餘額) 才是真實做空部位
- 早盤只看新借量是危險的（容易誤判方向）
- 一定要等收盤後 TWSE 公布的「當日賣出」「當日還券」「餘額變化」才下確定結論
- 範例教訓：2026-05-07 的 2313 早盤新借 2,000 張，看似空襲，實際當日賣出僅 120 張、還券 3,094 張，是空方大撤退

### ⚠️ 紀律 2：老空頭回補 vs 新空頭建倉
- **還券明細**含「借於 X 月 Y 日 持有 N 天 @ R% 利率」
- 看「借於 30+ 天 + 1.0% 低利率」的部位回補 = **老空頭獲利出場**（利多）
- 看「借於 7 天內 + 5%+ 高利率」的部位回補 = 短線投機客撤
- 看新借部位利率走勢：利率下降 = 借券需求降 = 做空意願退；利率走高 = 新空積極

### ⚠️ 紀律 3：三線方向必須交叉驗證
- 借券面 + 現股面 + 融資面要看一致性
- 例：今日 -8% 大跌 + 借券餘額 -10% + 外資現股 Top 賣 + 融資不變 → 外資現股出貨主導，不是空襲（2313 5/6 案例）
- 例：今日小漲 + 借券餘額 +5% + 外資現股 Top 買 + 融資增 → 多空對峙，外資多頭仍掌控
- 三線方向一致才能下強訊號；衝突時只下「籌碼結構轉變」中性結論

### ⚠️ 紀律 4：早盤別下結論，盤後也要等對時間
- 台股盤中 9:00-13:30 期間，TWSE 借券賣出餘額（TWT93U）尚未出來
- **13:30 收盤後約 21:30 才公布完整借券賣出餘額**（不是 15:00-17:00，那是上週搞錯的時間）
- 早盤 + 盤中 + 收盤後到 21:30 之間：只能跑出「借券交易（新借）」+「還券明細」+「分點截至上一交易日」，**僅供觀察**
- 必須在輸出時明確標註「等今晚 21:30 完整借券賣出餘額再給確定判讀」
- 21:30 後資料完整，可以下定論

### ⚠️ 紀律 5：交易日感知
- 抓近 N 日軌跡時跳過六日 + 國定假日
- 用既有工具的 cache（bsr_cache/、margin_cache/）會自然只有交易日資料

### ⚠️ 紀律 6：TWSE 還券明細 endpoint 偶爾 rate-limit
- `tw_lending_lookup.py` 大部分已遷到 FinMind（借入交易 + 借券賣出餘額），不會被 rate-limit
- **但「還券明細」(t13sa870) 仍由 TWSE 直接抓**，因為 FinMind 沒有 per-event 還券 + 借入日資料
- **2026-07-18 起工具內建 retry**（失敗自動等 25 秒重試最多 3 次，stderr 會印 `[WARN] t13sa870 attempt N/3`；全敗印 `[ERROR] ... 疑似 rate-limit`）— 看到 ERROR 才是真抓不到
- 如果 chip 報告「還券明細：無還券」但你預期應該有（如大跌日 / 餘額大減日），檢查 stderr 有無 ERROR；沒有 ERROR = 當天真的無契約還券
- 範例教訓：2026-05-11 2313 第一次 chip 顯示「無還券」是 TWSE rate-limit；2026-07-18 5347 敘事誤報 07/17 明細缺（當時無 retry）
- 注意 t13sa870 的 startDate/endDate 是**借入日**區間，不是還券日 — 查近期還券要用寬 startDate（如 20250101）再按 return_date 過濾

## FinMind Token 取得

從 crontab 抓（不要硬編碼）：
```bash
crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/'
```

## 範例輸出對照

參考 2026-05-06 ~ 5-7 對 2313 / 3491 的歷史 Telegram 訊息（msg 1258/1262/1270/1279/1281/1286/1300）— 那是手動模式，本 skill 自動化版本應該保持同樣的結構與紀律品質，輸出更穩定一致。

#!/usr/bin/env python3
"""
處置股新制解讀頁(2026-08 修正版)+ 千金股 11 款門檻即時監控。

級距門檻(注意第11款,6 營業日收盤價起迄價差):
  P ≤ 1,000        → 豁免
  1,000 < P ≤ 2,000 → 300 元
  之後每 +1,000 元一級距,門檻 +150 元(2,000-3,000 → 450,依此類推)
  → 每級距「頂端」容許幅度都是 15%,漸近線 = 6 日淨變動 15%(約 1.5 根漲停)

即時表資料:cache/year_prices/{date}.json(還原收盤;最新日=實際收盤)。
6 日起迄 = 最新收盤 − 往前第 5 個交易日收盤(共 6 個收盤)。
⚠ 還原價 caveat:6 日內有除權息的個股,還原價差 ≠ 實際價差(頁面註明)。
"""

import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def threshold(price: float) -> int | None:
    """11 款價差門檻(元)。≤1000 豁免回 None。"""
    if price <= 1000:
        return None
    if price <= 2000:
        return 300
    return 300 + 150 * (int((price - 2000) // 1000) + 1)


def _name_lookup():
    try:
        from stock_names import get_name
    except Exception:
        get_name = None
    try:
        fm = json.load(open(os.path.join(HERE, "cache", "finmind_names.json")))
        fm = fm.get("names", fm) if isinstance(fm, dict) else {}
    except Exception:
        fm = {}

    def name(code):
        if get_name:
            n = get_name(code, fallback="")
            if n and n != code:
                return n
        return fm.get(code, "")
    return name


def build_monitor_rows(min_price: float = 900.0) -> tuple[list[dict], str]:
    """回傳 (rows, 最新資料日)。rows 依門檻用掉% 降冪。
    只含 4 碼個股(排除指數/ETF 代碼)。"""
    files = sorted(glob.glob(os.path.join(HERE, "cache", "year_prices", "*.json")))
    if len(files) < 6:
        return [], "—"
    latest_date = os.path.basename(files[-1]).replace(".json", "")
    day_maps = [json.load(open(f)) for f in files[-6:]]
    name = _name_lookup()
    latest = day_maps[-1]
    first = day_maps[0]
    rows = []
    for code, v in latest.items():
        if not (len(code) == 4 and code.isdigit()):
            continue
        close = v[2] if isinstance(v, list) and len(v) >= 3 else None
        if not close or close < min_price:
            continue
        v0 = first.get(code)
        c0 = v0[2] if isinstance(v0, list) and len(v0) >= 3 else None
        diff = (close - c0) if c0 else None
        th = threshold(close)
        used = abs(diff) / th * 100 if (diff is not None and th) else None
        n_limit = math.log(1 + th / close) / math.log(1.10) if th else None
        rows.append({
            "code": code, "name": name(code), "close": close,
            "th": th, "diff": diff, "used": used,
            "allow_pct": th / close * 100 if th else None,
            "n_limit": n_limit,
        })
    rows.sort(key=lambda r: (-(r["used"] or -1), -r["close"]))
    return rows, latest_date


_TIER_TABLE = """
<table class="report-table">
<thead><tr><th>股價級距</th><th>價差門檻</th><th>6日容許幅度(級距底→頂)</th><th>約幾根漲停</th></tr></thead>
<tbody>
<tr><td>≤ 1,000 元</td><td><b>豁免</b></td><td>不適用第 11 款</td><td>—</td></tr>
<tr><td>1,000 ~ 2,000</td><td>300 元</td><td><b>30.0% → 15.0%</b></td><td>2.7 → 1.5 根</td></tr>
<tr><td>2,000 ~ 3,000</td><td>450 元</td><td>22.5% → 15.0%</td><td>2.1 → 1.5 根</td></tr>
<tr><td>3,000 ~ 4,000</td><td>600 元</td><td>20.0% → 15.0%</td><td>1.9 → 1.5 根</td></tr>
<tr><td>4,000 ~ 5,000</td><td>750 元</td><td>18.75% → 15.0%</td><td>1.8 → 1.5 根</td></tr>
<tr><td>5,000 ~ 6,000</td><td>900 元</td><td>18.0% → 15.0%</td><td>1.7 → 1.5 根</td></tr>
<tr><td>每 +1,000 元</td><td>+150 元</td><td>收斂到 <b>15%</b></td><td>→ 1.5 根</td></tr>
</tbody></table>
<p class="small">注意:容許幅度在「級距內」隨股價變動 — 級距底端(剛跨過整數關卡)緩衝最大、
級距頂端(貼近下一個整數關卡)只剩 15%。</p>
"""

_RULES_HTML = """
<section><h3>📋 新制四大修正(2026-08)</h3>
<ol>
<li><b>處置天數統一</b>:第 1 次與第 2 次(含)以上處置一律 <b>5 個營業日</b>;
若處置基數期間內曾被公布「注意第 13 款當沖比過高」→ 拉長為 <b>7 個營業日</b>。</li>
<li><b>撮合頻率放寬</b>:處置股撮合改為<b>約每 2 分鐘一次</b>
(原制第一次處置 5 分鐘、第二次 20 分鐘人工分盤)。
例外:變更交易方法/變更交易方法且分盤集合競價者不適用。</li>
<li><b>注意第 11 款門檻修正</b>:限縮為股價<b>逾 1,000 元</b>且 6 營業日收盤價起迄價差達
<b>300 元</b>以上才適用;逾 2,000 元部分每 1,000 元一級距,每級距門檻 <b>+150 元</b>。</li>
<li><b>新舊制銜接</b>:施行日仍在處置中者用新規則重算 —
天數已到者<b>施行日當天直接解除</b>,未到者處置到期滿;撮合頻率施行日起一律改 2 分鐘
(變更交易方法類除外)。</li>
</ol></section>

<section><h3>⭐ 總評:7 / 10</h3>
<p><b>加分</b>:高價股誤觸發修正方向正確(絕對金額門檻與股價掛鉤);
第 13 款當沖比過高加重到 7 天是精準打擊而非齊頭式懲罰;
天數統一 + 銜接規則乾淨無模糊空間。</p>
<p><b>扣分</b>:<b>二次處置嚇阻力大減</b> — 原本 20 分鐘人工分盤幾乎凍結流動性(主力最怕),
新制一律 2 分鐘,處置從「關禁閉」變「罰站」;
級距是階梯不是平滑線(鋸齒問題,見下);
1,000 元以下完全豁免第 11 款,900-1,000 元帶出現防線縫隙。</p></section>

<section><h3>🧩 七個關鍵解讀</h3>

<h4>1. 每個級距頂端的容許幅度都恰好是 15% — 這條規則的漸近線</h4>
<p>門檻每 +1,000 元加 150 元 → 邊際比率 15%。股價越高越貼近「6 日淨變動 15%(約 1.5 根漲停)」
這條線;級距內位置決定額外緩衝(1,000-2,000 級距底端最寬,可到 30%)。</p>

<h4>2. 鋸齒反轉:剛跨過整數關卡的股票拿到最大緩衝</h4>
<p>實例(2026-08-03 收盤):致茂 1,960 元容許 15.3%,嘉澤 2,005 元容許 22.4% —
股價高 45 元、容許幅度反而寬 7 個百分點。
<b>貼著級距頂(1,900-2,000、2,900-3,000…)的股票最容易觸發;剛站上整數關卡的最安全。</b>
懂規則的主力會「先推過 2,000 再噴」。若用平滑公式(如 150 元 + 股價×15%)就沒有這個套利空間 —
這是制度設計瑕疵。</p>

<h4>3. 「起迄價差」只看淨變動,不管路徑</h4>
<p>6 天內先噴 +25% 再跌回原點 → 起迄價差近 0,不觸發。
反而<b>緩漲不休息的趨勢股比暴漲暴跌的妖股更容易中</b> — 跟直覺相反。
主力若想避開,只要「漲三天、洗兩天」讓 6 日淨變動壓在門檻下即可 — 這條抓的是斜率不是波動。</p>

<h4>4. 跌也算:崩跌中的千金股會在下跌途中進處置</h4>
<p>價差是絕對值概念,6 天跌 15% 一樣觸發。高價電子股急殺段(歷次台光電、智邦式殺法)
會被丟進注意/處置 — 而新制 2 分鐘撮合的處置,反而變相<b>保護了下跌時的流動性</b>(可以出得掉)。</p>

<h4>5. 對比注意第 1 款(6 日累積漲幅 32%):第 11 款對千金股嚴格約一倍</h4>
<p>中低價股要 6 日漲 32% 才注意;千金股 15~30% 就中。修正後高價股仍被特別關照,
只是不再荒謬(舊制下信驊等級的正常波動就貼門檻)。</p>

<h4>6. 注意 ≠ 處置,但千金股主升段很容易湊滿處置要件</h4>
<p>處置要件是注意的累積:<b>連續 5 個營業日、或 10 日內 6 日、或 30 日內 12 日</b>被列注意。
第 11 款是 6 日滾動視窗 — 一段 20% 的主升段,每一天的視窗都超標,連續 5 天注意輕輕鬆鬆。
實務換算:<b>「1.5 根漲停的淨變動維持一週」≈ 處置入場券</b>。</p>

<h4>7. 施行日有「解禁潮」:一批處置股集體提前放出</h4>
<p>銜接規則=施行日用新制重算、天數已到直接解除 → 原第二次處置(舊制 10 天)者最受惠。
解除處置日歷來有流動性回補行情,施行日當天值得盯。</p>
</section>

"""

_STRATEGY_HTML = """
<section><h3>💡 可開發的策略構想(尚未開發,按價值排序)</h3>
<ol>
<li><b>11 款門檻雷達(本頁下方已上線)</b>:每日掃千金股 6 日起迄價差 ÷ 門檻,
用掉 ≥70% 的列預警。用途:持股者提前知道「再一根漲停就注意」;
交易者觀察「進注意前的最後衝刺」與「注意後降溫」型態。可加 cron 推播。</li>
<li><b>處置解禁行情回測</b>:抓 TWSE/TPEx 處置公告歷史,回測「解除處置日後 N 日」報酬與量能回補。
若有 edge,做解禁日曆 + 前一日提醒。新制施行日的集體解禁潮是天然實驗場。</li>
<li><b>注意累積計數器</b>:追每檔的注意次數(連 5 / 10 之 6 / 30 之 12 進度條),
量化「距處置還差幾天」。對隔日沖/當沖者是風控工具(處置股不能當沖、出場流動性變差)。</li>
<li><b>整數關卡跨越觀察</b>:鋸齒效應下,跨過 2,000/3,000 的千金股拿到寬鬆門檻 —
統計「跨關卡後 N 日動能是否強於未跨關卡對照組」。若成立,是規則紅利型動能訊號。</li>
<li><b>處置中動能延續研究(新制後才能做)</b>:2 分鐘撮合下處置股的動能延續 vs 舊制 5/20 分鐘 —
懲罰放輕後「處置照樣噴」的機率理論上升高,累積數據後可驗證。</li>
</ol>
<p class="small">1 可立即做(本頁已含雷達表);2-3 需要接 TWSE/TPEx 注意與處置公告資料源;
4-5 需累積新制施行後的數據。</p></section>
"""


def render_page(nav: str, glossary: str = "", fut_set: set | None = None) -> str:
    fut_set = fut_set or set()
    rows, asof = build_monitor_rows()
    trs = []
    for r in rows:
        star = "★" if r["code"] in fut_set else ""
        if r["th"] is None:
            trs.append(
                f'<tr class="exempt"><td data-kx="{r["code"]}" style="cursor:pointer">'
                f'{r["code"]} {r["name"]}{star}</td>'
                f'<td>{r["close"]:,.0f}</td><td colspan="4" class="small">'
                f'≤1,000 豁免(距適用門檻 {(1000 - r["close"]) / r["close"] * 100:+.1f}%)</td></tr>')
            continue
        used = r["used"] or 0
        cls = "u-hot" if used >= 70 else ("u-warm" if used >= 40 else "")
        d = r["diff"]
        arrow = "▲" if d > 0 else ("▼" if d < 0 else "—")
        trs.append(
            f'<tr class="{cls}"><td data-kx="{r["code"]}" style="cursor:pointer">'
            f'{r["code"]} {r["name"]}{star}</td>'
            f'<td>{r["close"]:,.0f}</td><td>{r["th"]:,}</td>'
            f'<td>{arrow}{abs(d):,.0f} 元</td>'
            f'<td><b>{used:.0f}%</b></td>'
            f'<td class="small">{r["allow_pct"]:.1f}% / {r["n_limit"]:.1f} 根</td></tr>')
    monitor = (
        f'<section><h3>📡 11 款門檻雷達 — 千金股即時監控(資料日 {asof})</h3>'
        '<p class="small">6 日起迄價差 = 最新收盤 − 往前第 5 個交易日收盤(還原價;'
        '6 日內有除權息者價差與實際略有出入)。<b>用掉% ≥70% 標紅</b> = 再約一根漲停/跌停'
        '就觸發注意第 11 款。900-1,000 元列出供追蹤「即將進入適用範圍」。點代號看 K 線。</p>'
        '<div class="table-scroll"><table class="report-table"><thead><tr>'
        '<th>股票</th><th>收盤</th><th>門檻(元)</th><th>6日起迄</th>'
        '<th title="6日起迄價差絕對值 ÷ 門檻">用掉%</th>'
        '<th title="此價位容許的 6 日幅度與約當漲停根數">容許幅度</th>'
        '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div></section>')

    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚖ 處置股新制解讀</title>
<style>
  body{{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1100px;margin:1em auto;padding:0 1em;}}
  h1{{font-size:1.4em;margin:.4em 0}}
  h3{{margin:.2em 0 .5em}} h4{{margin:1em 0 .3em;color:#4cc2ff}}
  section{{padding:12px 16px;margin-bottom:14px;border-radius:8px}}
  table.report-table{{width:100%;border-collapse:collapse;font-size:.9em}}
  table.report-table th,table.report-table td{{padding:6px 9px;text-align:right}}
  table.report-table td:first-child,table.report-table th:first-child{{text-align:left}}
  .small{{font-size:.84em;color:#8b98a9}}
  .u-hot td{{color:#ff6b6b;font-weight:600}}
  .u-warm td{{color:#e6c56a}}
  .exempt td{{opacity:.55}}
  ol li,p{{line-height:1.65}}
</style></head><body>{nav}
<h1>⚖ 處置股新制解讀(2026-08 修正)+ 千金股門檻雷達</h1>
<p class="small">本頁為規則解讀 + 自建監控,非官方資訊;實際注意/處置以交易所公告為準。
處置要件:連續 5 個營業日、或 10 日內 6 日、或 30 日內 12 日被公布注意。</p>
{_RULES_HTML}
<section><h3>📐 第 11 款級距門檻表</h3>{_TIER_TABLE}</section>
{monitor}
{_STRATEGY_HTML}
{glossary}
</body></html>"""

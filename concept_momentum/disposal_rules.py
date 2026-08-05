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


# ── 注意/處置現況(讀 tw_disposal_data 快取) ──────────────────
def _load_disposal(kind):
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(HERE))
    import tw_disposal_data as dd
    return dd.load_all(kind)


def _calendar():
    files = sorted(glob.glob(os.path.join(HERE, "cache", "year_prices", "*.json")))
    return [os.path.basename(f).replace(".json", "") for f in files]


def build_attention_status():
    """回傳 (rows, asof)。近 30 交易日有注意紀錄的 4 碼個股之處置進度
    + 處置中/即將解禁標記。rows 依(處置中優先, 進度降冪)排序。"""
    cal = _calendar()
    if not cal:
        return [], "—"
    asof = cal[-1]
    last30 = set(cal[-30:])
    last10 = set(cal[-10:])
    notices = {}
    for r in _load_disposal("notice"):
        c = r.get("code", "")
        if len(c) == 4 and c.isdigit() and r.get("date") in last30:
            notices.setdefault(c, {"name": r["name"], "dates": set()})
            notices[c]["dates"].add(r["date"])
    active_p, coming_release = {}, {}
    for r in _load_disposal("punish"):
        c = r.get("code", "")
        st, en = r.get("start"), r.get("end")
        if not (len(c) == 4 and c.isdigit() and st and en):
            continue
        if st <= asof <= en:
            active_p[c] = {"end": en, "measure": r.get("measure", ""),
                           "cum": r.get("cum", ""), "name": r.get("name", "")}
    rows = []
    seen = set(notices) | set(active_p)
    for c in seen:
        info = notices.get(c, {})
        dates = info.get("dates", set())
        streak = 0
        for d in reversed(cal[-30:]):
            if d in dates:
                streak += 1
            else:
                break
        n10 = len(dates & last10)
        n30 = len(dates)
        prog = max(streak / 5, n10 / 6, n30 / 12)
        disp = active_p.get(c)
        # 距解禁交易日數
        days_left = None
        if disp:
            days_left = len([d for d in cal if asof < d <= disp["end"]])
            future = [d for d in cal if d > asof]
            days_left = sum(1 for d in future if d <= disp["end"])
            if days_left == 0:          # 快取日曆沒有未來日,用日曆日估
                from datetime import datetime as _dt
                days_left = max(0, ( _dt.strptime(disp["end"], "%Y%m%d")
                                     - _dt.strptime(asof, "%Y%m%d")).days)
        rows.append({"code": c,
                     "name": info.get("name") or (disp or {}).get("name", ""),
                     "streak": streak, "n10": n10, "n30": n30,
                     "progress": prog, "disposed": bool(disp),
                     "disp_end": disp["end"] if disp else None,
                     "disp_left": days_left,
                     "measure": (disp or {}).get("measure", "")})
    rows.sort(key=lambda r: (not r["disposed"], -r["progress"]))
    return rows, asof


def _fmt_ymd(d):
    return f"{d[4:6]}/{d[6:]}" if d and len(d) == 8 else (d or "—")


def render_attention_section(fut_set=None):
    fut_set = fut_set or set()
    rows, asof = build_attention_status()
    if not rows:
        return ('<section><h3>🚨 現役注意/處置狀態</h3>'
                '<p class="small">近 30 交易日無注意/處置紀錄之 4 碼個股,'
                '或公告快取尚未建立(跑 tw_disposal_data.py)。</p></section>')
    trs = []
    for r in rows[:40]:
        star = "★" if r["code"] in fut_set else ""
        if r["disposed"]:
            st = (f'<span style="color:#ff6b6b;font-weight:700">處置中</span> '
                  f'至 {_fmt_ymd(r["disp_end"])}(剩 {r["disp_left"]} 交易日)')
        elif r["streak"] >= 4 or r["n10"] >= 5 or r["n30"] >= 10:
            st = '<span style="color:#e6c56a;font-weight:700">瀕臨處置</span>'
        else:
            st = ""
        trs.append(
            f'<tr><td data-kx="{r["code"]}" style="cursor:pointer">'
            f'{r["code"]} {r["name"]}{star}</td>'
            f'<td>{r["streak"]}/5</td><td>{r["n10"]}/6</td><td>{r["n30"]}/12</td>'
            f'<td>{r["progress"]*100:.0f}%</td><td>{st}</td></tr>')
    return (
        f'<section><h3>🚨 現役注意/處置狀態 — 距處置進度(資料日 {asof})</h3>'
        '<p class="small">處置要件三條路:<b>連續 5 日</b>注意、<b>10 日內 6 次</b>、'
        '<b>30 日內 12 次</b> — 任一達成即處置。進度 = 三者最大完成度。'
        '含權證以外之 4 碼個股;來源 TWSE/TPEx 公告(每日 20:20 更新)。⚠ 計數為近似:處置後累計歸零、同款別合併等交易所細則未完全模擬,會出現「進度>100% 但未處置」— 以交易所公告為準。</p>'
        '<div class="table-scroll"><table class="report-table"><thead><tr>'
        '<th>股票</th><th>連續</th><th>10日內</th><th>30日內</th>'
        '<th>進度</th><th>狀態</th></tr></thead><tbody>'
        + "".join(trs) + '</tbody></table></div></section>')


def render_tier_signal_section(fut_set=None):
    """整數關卡跨越訊號:近 5 交易日事件 + 逼近關卡 watch。"""
    fut_set = fut_set or set()
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(HERE))
    try:
        import tw_disposal_analysis as ta
        events = ta.recent_tier_events(5)
        watch = ta.near_tier_watch(5.0)
    except Exception:
        events, watch = [], []
    name = _name_lookup()

    def li(e, extra=""):
        star = "★" if e["code"] in fut_set else ""
        return (f'<tr><td data-kx="{e["code"]}" style="cursor:pointer">'
                f'{e["code"]} {name(e["code"])}{star}</td>'
                f'<td>{_fmt_ymd(e["date"])}</td><td>{e["tier"]:,}</td>'
                f'<td>{e["close"]:,.0f}</td><td>{extra}</td></tr>')
    try:
        import tw_disposal_analysis as _ta
        fz = _ta.free_zone_watch()
    except Exception:
        fz = []
    rows = "".join(li(e, "✅ 已跨越") for e in events)
    for w in watch:
        tag = f'差 {w["gap_pct"]}%'
        if w["tier"] >= 2000:
            tag += '(雷區→通關)'
        rows += li(w, tag)
    for w in fz:
        kind = "突破型" if w["first_time"] else "收復型"
        mom = f'{w["mom6"]:+.1f}%' if w["mom6"] is not None else "—"
        rows += (f'<tr><td data-kx="{w["code"]}" style="cursor:pointer">'
                 f'{w["code"]} {name(w["code"])}'
                 f'{"★" if w["code"] in fut_set else ""}</td>'
                 f'<td>{_fmt_ymd(w["date"])}</td><td>1,000</td>'
                 f'<td>{w["close"]:,.0f}</td>'
                 f'<td>🎯 免費區候補 差 {w["gap_pct"]}% · 6日動能 {mom} · {kind}</td></tr>')
    if not rows:
        rows = '<tr><td colspan="5" class="small">近 5 日無跨關卡事件,亦無逼近關卡(≤5%)標的。</td></tr>'
    return (
        '<section><h3>📈 整數關卡跨越訊號(策略選股)</h3>'
        '<p class="small">訊號:原始收盤<b>首次</b>站上 1,000/2,000/3,000…整數關卡'
        '(前 60 交易日未曾觸及)。回測(n=152,2024-07~2026-07):'
        '<b>H20 +10.3%、中位 +8.2%、勝率 61%</b> vs 同日高價股對照 +6.7%/+2.5%/55% — '
        '中位數也贏,非彩券分布。⚠ 回測樣本以 1,000-6,000 關卡為主,更高關卡為同邏輯外推;'
        '新制鋸齒紅利(跨關卡後 11 款門檻放寬)屬額外順風。'
        '「差 x%」= 逼近關卡預備名單(距上方 60 日未觸及關卡 ≤5%)。</p>'
        '<div class="table-scroll"><table class="report-table"><thead><tr>'
        '<th>股票</th><th>日期</th><th>關卡</th><th>收盤(原始)</th><th>狀態</th>'
        '</tr></thead><tbody>' + rows + '</tbody></table></div></section>')


def render_backtest_section():
    parts = []
    p1 = os.path.join(HERE, "cache", "disposal_backtest.json")
    if os.path.exists(p1):
        d = json.load(open(p1))
        h = d["horizons"]
        sp = d["splits"]
        def row(label, s):
            if not s:
                return ""
            return (f'<tr><td>{label}</td><td>{s["n"]}</td>'
                    f'<td>{s["mean"]:+.1f}%</td><td>{s["median"]:+.1f}%</td>'
                    f'<td>{s["win"]:.0f}%</td>'
                    f'<td>{s.get("excess_mean", "—"):+.1f}%</td>'
                    f'<td>{s.get("t", "—")}</td></tr>')
        parts.append(
            f'<section><h3>🧪 回測 A:處置解禁行情(解除日收盤進場,n={d["n_events"]},'
            f'{d["sample_range"][0][:4]}/{_fmt_ymd(d["sample_range"][0])}'
            f'~{d["sample_range"][1][:4]}/{_fmt_ymd(d["sample_range"][1])})</h3>'
            '<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>分組</th><th>n</th><th>絕對均</th><th>中位</th><th>勝率</th>'
            '<th>超額均(vs同日隨機100檔)</th><th>t</th></tr></thead><tbody>'
            + row("全部 H5", h["5"]) + row("全部 H10", h["10"]) + row("全部 H20", h["20"])
            + row("首次處置 H20", sp["first"]["20"])
            + row("二次+處置 H20", sp["second_plus"]["20"])
            + row("上市 H20", sp["twse"]["20"]) + row("上櫃 H20", sp["tpex"]["20"])
            + '</tbody></table></div>'
            f'<p><b>結論:解禁不是穩定 edge,是彩券。</b>H20 超額均 +3.7%(t=4.4)看似顯著,'
            f'但中位數 −2.3%、勝率僅 48% — 平均被少數解禁暴衝股拉高,買「一般」解禁股多數輸。'
            f'二次+處置解禁(H20 超額 +4.6%, t=4.3)強於首次(+1.9%, t=1.6),'
            f'與「被關越久反彈越大」一致。處置期間本身平均仍 <b>+{d["in_period_ret"]}%</b>'
            f'(n={d["in_period_n"]})— 處置壓不住動能。'
            '<b>可操作解讀:解禁日不無腦追;若要參與,偏向二次+處置且處置期間仍強者,'
            '並接受彩券式分布(小注分散)。</b></p></section>')
    p2 = os.path.join(HERE, "cache", "tier_cross_backtest.json")
    if os.path.exists(p2):
        d = json.load(open(p2))
        h, c = d["horizons"], d["control"]
        def row2(label, s):
            if not s:
                return ""
            return (f'<tr><td>{label}</td><td>{s["n"]}</td>'
                    f'<td>{s["mean"]:+.1f}%</td><td>{s["median"]:+.1f}%</td>'
                    f'<td>{s["win"]:.0f}%</td></tr>')
        parts.append(
            f'<section><h3>🧪 回測 B:整數關卡跨越(原始收盤首次站上 1000/2000/3000…,'
            f'n={d["n_events"]})</h3>'
            '<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>組別</th><th>n</th><th>絕對均</th><th>中位</th><th>勝率</th>'
            '</tr></thead><tbody>'
            + row2("跨關卡 H5", h["5"]) + row2("跨關卡 H10", h["10"]) + row2("跨關卡 H20", h["20"])
            + row2("對照(同日高價股) H5", c["5"]) + row2("對照 H10", c["10"])
            + row2("對照 H20", c["20"])
            + '</tbody></table></div>'
            '<p class="small">⚠ 此回測驗證的是「整數關卡心理效應」(新制鋸齒紅利只適用施行後,'
            '尚無數據可測)。事件偵測用原始收盤(關卡是名目價格),報酬用還原價。</p></section>')
    if not parts:
        parts.append('<section class="note">回測結果尚未產生'
                     '(跑 tw_disposal_analysis.py --release / --tier-cross)。</section>')
    return "".join(parts)


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

<h4>8. ⭐ 跨 1,000 是「免費區」— 規則無意間畫出的主力地圖</h4>
<p>1,000 元以下本來就有<b>第一款(6 日累積漲跌 32%)</b>人人適用的天花板管著;
剛跨過 1,000 後,11 款門檻 300 元 ≈ 30%,<b>與第一款的 32% 幾乎重疊</b> —
「站上千金」這一步在監管上零新增代價。完整地圖:</p>
<table class="report-table">
<thead><tr><th>區段</th><th>11款容許幅度</th><th>性質</th></tr></thead>
<tbody>
<tr><td>950 → 1,300</td><td>免疫 → 30%~23%</td><td><b>免費區</b>:跨千金無新約束,
且回測顯示首次站上 1,000 有動能順風(H20 +10.3%)</td></tr>
<tr><td>1,700 → 2,000</td><td>17.6% → 15%</td><td><b>雷區</b>:1.5 根漲停就見報注意,
連拉易湊處置</td></tr>
<tr><td>跨過 2,000/3,000…</td><td>跳回 22.5%/20%…</td><td><b>快速通關</b>:貼級距頂別磨、
直接推過去,門檻立刻放寬</td></tr>
</tbody></table>
<p>加上「起迄只看淨變動」(漲三洗二可控)與新制處置僅 5 天 2 分鐘,
這套規則對懂它的人是操作說明書、對不懂的人才是限制。
下方「千元免費區候補」即依此特性選股。</p>
</section>

"""

_STRATEGY_HTML = """
<section><h3>💡 可開發的策略構想(尚未開發,按價值排序)</h3>
<ol>
<li><b>11 款門檻雷達 ✅ 已上線</b>(本頁雷達表 + 每日 20:20 cron,
≥70%/瀕臨處置/即將解禁任一觸發才推 Telegram)。</li>
<li><b>處置解禁行情回測 ✅ 已完成</b>(結果見上方回測 A:解禁是彩券 —
平均正但中位負;二次+處置解禁較強;推播附解禁日提醒)。</li>
<li><b>注意累積計數器 ✅ 已上線</b>(上方「現役注意/處置狀態」表,
每日 cron 更新公告快取)。</li>
<li><b>整數關卡跨越 ✅ 已回測</b>(結果見上方回測 B:跨關卡後動能顯著強於同日高價股對照,
中位數也贏 — 圓整數突破效應成立;新制鋸齒紅利屬額外順風,施行後可再驗)。</li>
<li><b>處置中動能延續研究(累積中)</b>:公告快取每日累積(2024-07 起已回補),
新制施行滿 2-3 個月後可對比新舊制處置期間報酬(舊制基期:處置期間均 +3.4%)。</li>
</ol>
<p class="small">資料源:TWSE announcement/notice+punish、TPEx bulletin/attention+disposal
(官方 API,月檔快取於 cache/disposal/,2024-07 起)。</p></section>
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
{render_tier_signal_section(fut_set)}
{render_attention_section(fut_set)}
{render_backtest_section()}
{_STRATEGY_HTML}
{glossary}
</body></html>"""

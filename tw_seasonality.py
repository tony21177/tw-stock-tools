#!/usr/bin/env python3
"""
月份季節性 / 月曆效應 (tw_seasonality)

兩大區塊:

A. 指數月份季節性 —— 找「慣性」(元月效應、作夢行情、Sell in May、紅色十月…)
   標的: 加權 ^TWII、S&P500 ^GSPC、Nasdaq ^IXIC、費半 ^SOX、道瓊 ^DJI (Yahoo 月線),
         櫃買 OTC (FinMind TaiwanStockPrice data_id=TPEx)、
         台指期 TX 近月連續 (FinMind TaiwanFuturesDaily)。
   每個日曆月 (1~12月) 統計: 樣本年數 / 上漲勝率% / 平均報酬% / 中位數% / 最佳年 / 最差年 / 標準差。
   跨指數比較熱力表 + 加權&S&P 的「年×月」熱力矩陣。

B. 台股月份漲停/跌停家數 —— 投機熱度的季節性 (台股限定)
   FinMind TaiwanStockPriceAdj 全市場逐日 (~2500 檔,不含權證),
   4 位數普通股中每日數漲停 (漲幅≥9.5%) / 跌停 (≤-9.5%) 家數,按日曆月聚合。
   ⚠ 台股漲跌幅限制 2015-06 由 7% 改 10%,故只算 2015-06 起 (10% 制度可比)。

顏色遵台股慣例: 紅=漲、綠=跌。

資料來源: Yahoo Finance (指數月線) + FinMind (櫃買/台指期/全市場漲停家數)。
用法:
  python3 tw_seasonality.py --backfill-limitup   # 補全市場漲停家數逐日快取 (背景,首次數十分鐘)
  python3 tw_seasonality.py --build              # 重算並寫 cache/seasonality_latest.json
  python3 tw_seasonality.py --html > /tmp/s.html # 產生網頁 (debug)
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from finmind_client import _call as fm_call  # noqa: E402

CACHE_DIR = os.path.join(HERE, "concept_momentum", "cache")  # 網頁 route 讀此處
SEASON_DIR = os.path.join(CACHE_DIR, "season")           # index monthly series cache
LIMITUP_DIR = os.path.join(CACHE_DIR, "season_limitup")  # per-day 漲停家數 cache
os.makedirs(SEASON_DIR, exist_ok=True)
os.makedirs(LIMITUP_DIR, exist_ok=True)
LATEST = os.path.join(CACHE_DIR, "seasonality_latest.json")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

LIMITUP_START = "2015-06-01"   # 10% 漲跌幅制度上路
LIMIT_PCT = 9.5                # 判漲/跌停門檻 (含跳動誤差)

# 指數清單: (id, 中文名, 來源)
YAHOO_INDICES = [
    ("TWII", "加權指數", "^TWII"),
    ("GSPC", "S&P 500", "^GSPC"),
    ("IXIC", "Nasdaq", "^IXIC"),
    ("SOX", "費城半導體", "^SOX"),
    ("DJI", "道瓊工業", "^DJI"),
]
MONTH_LABELS = ["", "1月", "2月", "3月", "4月", "5月", "6月",
                "7月", "8月", "9月", "10月", "11月", "12月"]


# ───────────────────────── 資料抓取: 指數月線 ─────────────────────────
def _yahoo_monthly(symbol: str, rng: str = "25y") -> list[tuple[str, float]]:
    """Yahoo 月線 → [(YYYY-MM, month_end_close), ...] (升冪)。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1mo&range={rng}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode())
        r = data["chart"]["result"][0]
        ts = r.get("timestamp", [])
        cl = r.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    except Exception:
        return []
    out = []
    for t, c in zip(ts, cl):
        if c is None:
            continue
        ym = datetime.fromtimestamp(t).strftime("%Y-%m")
        out.append((ym, float(c)))
    # Yahoo 月線最後一根是「當月」(未收月),月度統計會把當月剔除 (見 monthly_returns)
    return out


def _finmind_daily_to_monthly(rows: list[dict], close_key: str = "close") -> list[tuple[str, float]]:
    """FinMind 日線 rows → 每月最後交易日收盤 → [(YYYY-MM, close), ...] 升冪。"""
    by_month: dict[str, tuple[str, float]] = {}
    for r in rows:
        d = r.get("date", "")
        c = r.get(close_key)
        if not d or c is None:
            continue
        ym = d[:7]
        # 保留該月最大日期
        if ym not in by_month or d > by_month[ym][0]:
            by_month[ym] = (d, float(c))
    return [(ym, v[1]) for ym, v in sorted(by_month.items())]


def _finmind_index_monthly(data_id: str, token: str, start: str = "2004-01-01") -> list[tuple[str, float]]:
    rows = fm_call("TaiwanStockPrice", {"data_id": data_id, "start_date": start}, token)
    return _finmind_daily_to_monthly(rows)


def _tx_monthly(token: str, start_year: int = 2005) -> list[tuple[str, float]]:
    """台指期 TX 近月連續月線 (每月最後交易日的近月收盤)。逐年抓避免 payload 過大。"""
    daily: dict[str, tuple[str, float]] = {}  # date -> (contract_date, close) 取近月
    this_year = date.today().year
    for yr in range(start_year, this_year + 1):
        try:
            rows = fm_call("TaiwanFuturesDaily", {
                "data_id": "TX",
                "start_date": f"{yr}-01-01",
                "end_date": f"{yr}-12-31",
            }, token)
        except Exception:
            continue
        for r in rows:
            if r.get("trading_session") != "position":
                continue
            d = r.get("date", "")
            cd = str(r.get("contract_date", ""))
            c = r.get("close")
            if not d or not cd.isdigit() or c is None or c <= 0:
                continue
            ymnum = d[:4] + d[5:7]            # 該交易日所屬 YYYYMM
            if cd < ymnum:                    # 已到期合約跳過
                continue
            # 取「近月」= 最小 contract_date >= 當月
            if d not in daily or cd < daily[d][0]:
                daily[d] = (cd, float(c))
        time.sleep(0.3)
    monthly: dict[str, tuple[str, float]] = {}
    for d, (cd, c) in daily.items():
        ym = d[:7]
        if ym not in monthly or d > monthly[ym][0]:
            monthly[ym] = (d, c)
    return [(ym, v[1]) for ym, v in sorted(monthly.items())]


# ───────────────────────── 統計: 月份季節性 ─────────────────────────
def monthly_returns(series: list[tuple[str, float]]) -> list[tuple[int, int, float]]:
    """月末收盤序列 → [(year, month, ret_pct), ...]。剔除未收月 (最後一根若為當月)。"""
    if len(series) < 2:
        return []
    cur_ym = date.today().strftime("%Y-%m")
    out = []
    for i in range(1, len(series)):
        ym, c = series[i]
        _, prev = series[i - 1]
        if ym == cur_ym:      # 當月尚未收月,不納入季節統計
            continue
        if prev <= 0:
            continue
        y, m = int(ym[:4]), int(ym[5:7])
        out.append((y, m, (c / prev - 1.0) * 100.0))
    return out


def seasonality_stats(rets: list[tuple[int, int, float]]) -> dict:
    """依日曆月彙總。回傳 {month: {n, win, avg, med, std, best, worst}}。"""
    buckets: dict[int, list[tuple[int, float]]] = {m: [] for m in range(1, 13)}
    for y, m, r in rets:
        buckets[m].append((y, r))
    out = {}
    for m in range(1, 13):
        vals = buckets[m]
        if not vals:
            out[m] = None
            continue
        rs = [v for _, v in vals]
        best = max(vals, key=lambda x: x[1])
        worst = min(vals, key=lambda x: x[1])
        out[m] = {
            "n": len(rs),
            "win": round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1),
            "avg": round(sum(rs) / len(rs), 2),
            "med": round(statistics.median(rs), 2),
            "std": round(statistics.pstdev(rs), 2) if len(rs) > 1 else 0.0,
            "best": {"year": best[0], "val": round(best[1], 2)},
            "worst": {"year": worst[0], "val": round(worst[1], 2)},
        }
    return out


def year_month_matrix(rets: list[tuple[int, int, float]]) -> dict:
    """{year: {month: ret}} for 年×月 熱力矩陣。"""
    mat: dict[int, dict[int, float]] = {}
    for y, m, r in rets:
        mat.setdefault(y, {})[m] = round(r, 2)
    return mat


def build_index_block(idx_id: str, name: str, series: list[tuple[str, float]]) -> dict:
    rets = monthly_returns(series)
    stats = seasonality_stats(rets)
    years = sorted({y for y, _, _ in rets})
    return {
        "id": idx_id,
        "name": name,
        "window": f"{years[0]}~{years[-1]}" if years else "—",
        "n_years": len(years),
        "months": stats,
        "matrix": year_month_matrix(rets),
    }


# ───────────────────────── Part B: 全市場漲停/跌停家數 ─────────────────────────
def _is_common(sid: str) -> bool:
    """4 位數普通股 (排除權證 6+位、ETF/ETN 00 開頭、特別股/TDR 帶字母)。"""
    return len(sid) == 4 and sid.isdigit() and sid[0] != "0"


def _limitup_day(date_iso: str, token: str) -> dict | None:
    """單日全市場漲停/跌停家數。cache season_limitup/{date}.json。回傳 {lu,ld,n}。"""
    cache = os.path.join(LIMITUP_DIR, f"{date_iso}.json")
    if os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        rows = fm_call("TaiwanStockPriceAdj",
                       {"start_date": date_iso, "end_date": date_iso}, token)
    except Exception:
        return None
    if not rows:
        return None
    lu = ld = n = 0
    for r in rows:
        sid = r.get("stock_id", "")
        if not _is_common(sid):
            continue
        c = r.get("close")
        s = r.get("spread")
        if not c or s is None:
            continue
        prev = c - s
        if prev <= 0:
            continue
        n += 1
        pct = s / prev * 100.0
        if pct >= LIMIT_PCT:
            lu += 1
        elif pct <= -LIMIT_PCT:
            ld += 1
    rec = {"lu": lu, "ld": ld, "n": n}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return rec


def _trading_dates(token: str, start: str = LIMITUP_START) -> list[str]:
    """自加權指數日線取得交易日曆 (YYYY-MM-DD)。"""
    rows = fm_call("TaiwanStockPrice", {"data_id": "TAIEX", "start_date": start}, token)
    return sorted({r["date"] for r in rows if r.get("date")})


def backfill_limitup(token: str, start: str = LIMITUP_START) -> int:
    """補全 2015-06 起每個交易日的漲停家數快取。可重複執行 (已快取則跳過)。"""
    dates = _trading_dates(token, start)
    done = 0
    for i, d in enumerate(dates):
        cache = os.path.join(LIMITUP_DIR, f"{d}.json")
        if os.path.exists(cache):
            continue
        rec = _limitup_day(d, token)
        if rec is not None:
            done += 1
        if done % 50 == 0 and done:
            print(f"  backfill … {d} ({done} new, {i+1}/{len(dates)})", flush=True)
        time.sleep(0.35)
    return done


def aggregate_limitup() -> dict:
    """讀取所有已快取日 → 依日曆月彙總。partial 也可用。"""
    per_ym: dict[str, dict[str, int]] = {}  # 'YYYY-MM' -> {lu,ld,days}
    covered = []
    for fn in os.listdir(LIMITUP_DIR):
        if not fn.endswith(".json"):
            continue
        d = fn[:-5]
        try:
            with open(os.path.join(LIMITUP_DIR, fn), encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        covered.append(d)
        ym = d[:7]
        b = per_ym.setdefault(ym, {"lu": 0, "ld": 0, "days": 0})
        b["lu"] += rec["lu"]
        b["ld"] += rec["ld"]
        b["days"] += 1
    # 依日曆月: 先算每個 (year,month) 的日均家數,再跨年平均
    by_month: dict[int, list[tuple[float, float]]] = {m: [] for m in range(1, 13)}
    for ym, b in per_ym.items():
        if b["days"] == 0:
            continue
        m = int(ym[5:7])
        by_month[m].append((b["lu"] / b["days"], b["ld"] / b["days"]))
    months = {}
    for m in range(1, 13):
        vals = by_month[m]
        if not vals:
            months[m] = None
            continue
        lu_avg = sum(v[0] for v in vals) / len(vals)
        ld_avg = sum(v[1] for v in vals) / len(vals)
        months[m] = {
            "lu": round(lu_avg, 1),          # 平均每交易日漲停家數
            "ld": round(ld_avg, 1),          # 平均每交易日跌停家數
            "net": round(lu_avg - ld_avg, 1),
            "ratio": round(lu_avg / ld_avg, 2) if ld_avg > 0.05 else None,
            "years": len(vals),
        }
    covered.sort()
    return {
        "start": LIMITUP_START,
        "months": months,
        "days_covered": len(covered),
        "range": (f"{covered[0]}~{covered[-1]}" if covered else "—"),
    }


# ───────────────────────── build ─────────────────────────
def build(token: str | None = None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    indices = []
    for idx_id, name, sym in YAHOO_INDICES:
        s = _yahoo_monthly(sym)
        if s:
            indices.append(build_index_block(idx_id, name, s))
    # 櫃買 OTC
    if token:
        try:
            otc = _finmind_index_monthly("TPEx", token)
            if otc:
                indices.append(build_index_block("OTC", "櫃買指數", otc))
        except Exception:
            pass
        try:
            tx = _tx_monthly(token)
            if tx:
                indices.append(build_index_block("TX", "台指期(近月)", tx))
        except Exception:
            pass

    # 跨指數比較 (月平均報酬)
    cross = {}
    for m in range(1, 13):
        cross[m] = {b["id"]: (b["months"][m]["avg"] if b["months"].get(m) else None)
                    for b in indices}

    limitup = aggregate_limitup()

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "indices": indices,
        "cross": cross,
        "limitup": limitup,
    }


def build_and_save(token: str | None = None) -> dict:
    data = build(token)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


# ───────────────────────── render ─────────────────────────
def _heat(v, scale=6.0):
    """報酬熱力色 (台股: 紅=漲、綠=跌)。回傳 (bg, fg)。"""
    if v is None:
        return "#fafafa", "#bbb"
    a = min(abs(v) / scale, 1.0)
    if v >= 0:
        return f"rgba(192,57,43,{0.10 + 0.62 * a:.2f})", ("#fff" if a > 0.55 else "#5a1a12")
    return f"rgba(10,138,58,{0.10 + 0.62 * a:.2f})", ("#fff" if a > 0.55 else "#0a4a24")


def render_html(data: dict) -> str:
    import html as _h
    nav = __import__("site_nav").nav_html("/seasonality")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1040px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06);overflow-x:auto;}
  table{border-collapse:collapse;font-size:.84em;width:100%;}
  th,td{padding:4px 7px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;}
  th{background:#eef2f7;color:#333;} thead th{position:sticky;top:0;z-index:2;}
  th.lft,td.lft{text-align:left;}
  .up{color:#c0392b;} .dn{color:#0a8a3a;}
  .hot{background:#c0392b;color:#fff;border-radius:3px;padding:0 5px;}
  .cold{background:#0a8a3a;color:#fff;border-radius:3px;padding:0 5px;}
  .small{font-size:.85em;color:#666;} b.k{color:#c0392b;}
  .note{background:#fff9ec;border:1px solid #f0dca8;border-radius:6px;
        padding:10px 14px;font-size:.86em;line-height:1.65;}
  td.hm{text-align:center;font-size:.8em;}
  caption{text-align:left;font-weight:600;padding:4px 0;color:#444;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>月份季節性 / 月曆效應</title>{css}</head><body>{nav}'
            f'<h1>📅 月份季節性 (月曆效應)</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'

    idxs = data.get("indices", [])
    as_of = data.get("as_of", "")

    # ── Section 1: 跨指數月平均報酬熱力表 ──
    cross = data.get("cross", {})
    s1 = ['<section><h3>① 跨指數 · 各月平均報酬% (紅=漲 綠=跌)</h3>',
          '<p class="small">每格 = 該指數該月歷史平均月報酬。整排偏紅=全球該月同步偏強。</p>',
          '<table><thead><tr><th class="lft">指數</th><th class="lft">樣本</th>']
    for m in range(1, 13):
        s1.append(f'<th>{m}月</th>')
    s1.append('</tr></thead><tbody>')
    for b in idxs:
        s1.append(f'<tr><td class="lft"><b>{_h.escape(b["name"])}</b></td>'
                  f'<td class="lft small">{b["window"]}<br>{b["n_years"]}年</td>')
        for m in range(1, 13):
            v = cross.get(str(m), cross.get(m, {})).get(b["id"]) if cross else None
            bg, fg = _heat(v)
            txt = f'{v:+.1f}' if v is not None else '—'
            s1.append(f'<td class="hm" style="background:{bg};color:{fg}">{txt}</td>')
        s1.append('</tr>')
    s1.append('</tbody></table></section>')

    # ── Section 2: 每指數詳細季節表 ──
    s2 = ['<section><h3>② 各指數月份季節統計</h3>']
    for b in idxs:
        s2.append(f'<table style="margin-bottom:14px"><caption>{_h.escape(b["name"])}'
                  f' · {b["window"]} ({b["n_years"]}年)</caption><thead><tr>'
                  '<th class="lft">月</th><th>樣本</th><th>上漲勝率</th><th>平均</th>'
                  '<th>中位</th><th>標準差</th><th>最佳年</th><th>最差年</th></tr></thead><tbody>')
        for m in range(1, 13):
            st = b["months"].get(str(m), b["months"].get(m))
            if not st:
                s2.append(f'<tr><td class="lft">{m}月</td><td colspan="7" class="small">—</td></tr>')
                continue
            wr = st["win"]
            wr_cls = "hot" if wr >= 65 else ("cold" if wr <= 35 else "")
            wr_html = f'<span class="{wr_cls}">{wr:.0f}%</span>' if wr_cls else f'{wr:.0f}%'
            avg_cls = "up" if st["avg"] >= 0 else "dn"
            s2.append(
                f'<tr><td class="lft">{m}月</td><td>{st["n"]}</td><td>{wr_html}</td>'
                f'<td class="{avg_cls}">{st["avg"]:+.2f}%</td>'
                f'<td class="{"up" if st["med"]>=0 else "dn"}">{st["med"]:+.2f}%</td>'
                f'<td class="small">{st["std"]:.1f}</td>'
                f'<td class="up small">{st["best"]["year"]} {st["best"]["val"]:+.1f}%</td>'
                f'<td class="dn small">{st["worst"]["year"]} {st["worst"]["val"]:+.1f}%</td></tr>')
        s2.append('</tbody></table>')
    s2.append('</section>')

    # ── Section 3: 年×月 熱力矩陣 (加權 + S&P) ──
    def matrix_table(b):
        mat = b.get("matrix", {})
        years = sorted(mat.keys(), key=lambda x: int(x), reverse=True)
        h = [f'<table style="margin-bottom:14px"><caption>{_h.escape(b["name"])} · 年×月報酬%'
             f' (紅=漲 綠=跌)</caption><thead><tr><th class="lft">年</th>']
        for m in range(1, 13):
            h.append(f'<th>{m}</th>')
        h.append('<th>全年</th></tr></thead><tbody>')
        for y in years:
            row = mat[y]
            yr_sum = 1.0
            cells = []
            for m in range(1, 13):
                v = row.get(str(m), row.get(m))
                bg, fg = _heat(v)
                cells.append(f'<td class="hm" style="background:{bg};color:{fg}">'
                             f'{v:+.0f}</td>' if v is not None else '<td class="hm">·</td>')
                if v is not None:
                    yr_sum *= (1 + v / 100)
            yr = (yr_sum - 1) * 100
            bg, fg = _heat(yr, scale=25)
            h.append(f'<tr><td class="lft"><b>{y}</b></td>' + "".join(cells)
                     + f'<td class="hm" style="background:{bg};color:{fg}"><b>{yr:+.0f}</b></td></tr>')
        h.append('</tbody></table>')
        return "".join(h)

    s3 = ['<section><h3>③ 年×月 報酬熱力矩陣</h3>',
          '<p class="small">看季節性是穩定存在,還是被少數大漲/大跌年份拉偏。</p>']
    for b in idxs:
        if b["id"] in ("TWII", "GSPC"):
            s3.append(matrix_table(b))
    s3.append('</section>')

    # ── Section 4: 台股漲停/跌停家數月份 ──
    lu = data.get("limitup", {})
    lm = lu.get("months", {})
    s4 = [f'<section><h3>④ 台股 · 各月漲停/跌停家數 (投機熱度季節性)</h3>',
          f'<p class="small">全市場 4 位數普通股,平均<b>每交易日</b>漲停/跌停家數。'
          f'涵蓋 {_h.escape(str(lu.get("range","—")))}({lu.get("days_covered",0)} 交易日)。'
          f'⚠ 台股漲跌幅 2015-06 由 7% 改 10%,故僅算 {_h.escape(str(lu.get("start","")))} 起(制度可比)。</p>',
          '<table><thead><tr><th class="lft">月</th><th>樣本年</th>'
          '<th>日均漲停</th><th>日均跌停</th><th>淨(漲-跌)</th><th>漲/跌比</th></tr></thead><tbody>']
    for m in range(1, 13):
        st = lm.get(str(m), lm.get(m))
        if not st:
            s4.append(f'<tr><td class="lft">{m}月</td><td colspan="5" class="small">—</td></tr>')
            continue
        net = st["net"]
        ratio = st["ratio"]
        s4.append(
            f'<tr><td class="lft">{m}月</td><td>{st["years"]}</td>'
            f'<td class="up">{st["lu"]:.1f}</td>'
            f'<td class="dn">{st["ld"]:.1f}</td>'
            f'<td class="{"up" if net>=0 else "dn"}">{net:+.1f}</td>'
            f'<td>{ratio if ratio is not None else "—"}</td></tr>')
    s4.append('</tbody></table></section>')

    glossary = """<section class="note">📖 <b>術語白話</b><br>
• <b>上漲勝率</b>:該月歷史上收紅(月報酬>0)的年份比例。≥65% 標紅(強季節慣性)、≤35% 標綠(弱)。<br>
• <b>平均/中位報酬</b>:該月月報酬的平均數與中位數。中位數較不受單一極端年份影響,兩者差很多代表分布偏。<br>
• <b>標準差</b>:該月報酬的波動大小;數字越大代表「該月慣性越不穩、越賭運氣」。<br>
• <b>最佳年/最差年</b>:該月歷史上最強與最弱的一次(年份+報酬),用來看極端值。<br>
• <b>年×月矩陣</b>:每一年每一個月的實際月報酬。整欄同色=季節性穩定;若靠一兩個大年份撐,就別太當真。<br>
• <b>日均漲停/跌停家數</b>:該月平均每個交易日有幾檔普通股鎖漲停/跌停,是「散戶投機熱度」的季節指標。<br>
• <b>顏色</b>:遵台股慣例 <b class="k">紅=漲</b>、<span style="color:#0a8a3a">綠=跌</span>。<br>
⚠ <b>季節性≠必然</b>:這是歷史統計慣性,不是保證;近年結構(升息、AI、被動資金)可能改變月曆效應,務必配合當下基本面/籌碼判讀,非買賣訊號。</section>"""

    foot = f'<p class="small">🕙 每月 1 號重建 · 更新於 {_h.escape(as_of)}</p>'
    return (head + "".join(s1) + "".join(s2) + "".join(s3) + "".join(s4)
            + glossary + foot + '</body></html>')


# ───────────────────────── CLI ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="重算並寫 seasonality_latest.json")
    ap.add_argument("--backfill-limitup", action="store_true", help="補全漲停家數逐日快取")
    ap.add_argument("--start", default=LIMITUP_START)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")

    if args.backfill_limitup:
        if not token:
            print("需要 FINMIND_TOKEN"); sys.exit(1)
        n = backfill_limitup(token, args.start)
        print(f"漲停家數快取新增 {n} 日 → {LIMITUP_DIR}")
        return
    if args.html:
        data = None
        if os.path.exists(LATEST):
            with open(LATEST, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = build(token)
        sys.stdout.write(render_html(data))
        return
    # default / --build
    data = build_and_save(token)
    n_idx = len(data["indices"])
    print(f"寫入 {LATEST}: {n_idx} 指數, 漲停家數涵蓋 {data['limitup']['days_covered']} 交易日")
    for b in data["indices"]:
        pos = [m for m in range(1, 13) if b["months"].get(m) and b["months"][m]["win"] >= 65]
        neg = [m for m in range(1, 13) if b["months"].get(m) and b["months"][m]["win"] <= 35]
        print(f"  {b['name']:10} {b['window']} 強月={pos} 弱月={neg}")


if __name__ == "__main__":
    main()

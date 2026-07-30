#!/usr/bin/env python3
"""明天大盤預期 (tw_market_overnight)

用「隔夜訊號」預測隔天台股加權指數(TAIEX)的方向/幅度(%與點數)/區間。
prediction 當下(美股收盤後~隔天開盤前)可得的訊號:
  ^SOX 費半、^IXIC 那斯達克、^GSPC 標普、TSM 台積電 ADR 的隔夜報酬,
  外加「台指期夜盤」報酬(15:00→05:00,把美股收盤後+亞洲+台灣本地的
  新聞/事件都定價進去,是隔夜新聞的即時聚合器)。
滾動 OLS(前 W 日)→ 預測隔天 TAIEX 收-收 與 開盤跳空,附校準信心帶。

⚠ 只預測「大盤」——回測 walk-forward:美股+夜盤 跳空方向 87%、收-收 76%,
  skill +19~24%。個股方向救不了(市場成分被個股雜訊蓋過),故只做指數;
  個股請把此當「背景風向」。

資料源:Yahoo(美股/ADR/加權指數,data_fetcher)+ FinMind(台指期夜盤)。
夜盤缺資料(FinMind 未更新)時自動退回「美股 4 項」模型(仍 ~84%)。
用法:
  tw_market_overnight.py                 # 明天大盤預期
  tw_market_overnight.py --backtest      # walk-forward 回測
  tw_market_overnight.py --line-to a,b   # 推播
"""
from __future__ import annotations
import argparse
import bisect
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
RAW_CACHE = os.path.join(CACHE, "overnight_us.json")
NIGHT_CACHE = os.path.join(CACHE, "tx_night.json")
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
sys.path.insert(0, HERE)

US_SYMBOLS = ["^SOX", "^IXIC", "^GSPC", "TSM"]
TWII = "^TWII"
WINDOW = 120                 # 滾動擬合視窗(交易日)
FINMIND = "https://api.finmindtrade.com/api/v4/data"


# ── 資料:Yahoo 美股/指數 ──────────────────────────────
def _fetch_raw(rng: str = "2y", max_age_h: float = 6.0) -> dict:
    if os.path.exists(RAW_CACHE):
        if (time.time() - os.path.getmtime(RAW_CACHE)) / 3600 < max_age_h:
            try:
                with open(RAW_CACHE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    import data_fetcher as df
    out = {}
    for sym in US_SYMBOLS + [TWII]:
        r = df.fetch_yahoo(sym, rng) or []
        out[sym] = [{"date": x["date"], "open": x["open"], "close": x["close"]}
                    for x in r]
    if all(out.get(s) for s in US_SYMBOLS + [TWII]):
        os.makedirs(CACHE, exist_ok=True)
        tmp = RAW_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, RAW_CACHE)
    return out


# ── 資料:台指期夜盤(FinMind)────────────────────────────
def _finmind_token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        import subprocess
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    except Exception:
        pass
    return ""


def fetch_night_returns(token: str = "", start: str = "2025-01-01",
                        max_age_h: float = 6.0) -> dict:
    """台指期夜盤報酬 {TW日 YYYYMMDD → %}。

    ⚠ FinMind 'after_market' session 掛在「結束日 D」(跑 D-1 傍晚→D 清晨),
    故夜盤報酬 = 夜盤收(D) / 前一交易日日盤收(D-1) − 1,用同一口契約,對齊
    當日(D)開盤。抓失敗/無 token 回空 dict(模型自動退回美股 4 項)。"""
    if os.path.exists(NIGHT_CACHE):
        if (time.time() - os.path.getmtime(NIGHT_CACHE)) / 3600 < max_age_h:
            try:
                with open(NIGHT_CACHE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    token = token or _finmind_token()
    if not token:
        return {}
    try:
        p = {"dataset": "TaiwanFuturesDaily", "data_id": "TX",
             "start_date": start, "token": token}
        u = FINMIND + "?" + urllib.parse.urlencode(p)
        with urllib.request.urlopen(u, timeout=60) as r:
            data = json.load(r).get("data", [])
    except Exception:
        return {}
    byd = defaultdict(lambda: {"position": {}, "after_market": {}})
    for r in data:
        cd = str(r.get("contract_date", ""))
        if len(cd) == 6 and r.get("trading_session") in ("position", "after_market") \
                and r.get("close"):
            byd[r["date"]][r["trading_session"]][cd] = r["close"]
    days = sorted(byd)
    night = {}
    for k in range(1, len(days)):
        D, P = days[k], days[k - 1]
        nt = byd[D]["after_market"]
        pos = byd[P]["position"]
        common = (sorted(c for c in nt if c in pos and c >= P[:6])
                  or sorted(c for c in nt if c in pos))
        if common:
            C = common[0]
            night[D.replace("-", "")] = round((nt[C] / pos[C] - 1) * 100, 3)
    if night:
        os.makedirs(CACHE, exist_ok=True)
        tmp = NIGHT_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(night, f)
        os.replace(tmp, NIGHT_CACHE)
    return night


def _overnight_ret(rows: list[dict]) -> dict:
    d = [r["date"] for r in rows]
    c = [r["close"] for r in rows]
    return {d[i]: (c[i] / c[i - 1] - 1) * 100
            for i in range(1, len(d)) if c[i - 1] > 0}


def build_dataset(raw: dict, night: dict | None = None) -> tuple[list, list[str]]:
    """→ ([(twdate, feat[], cc, gap)], 特徵名)。feat = 美股隔夜(4);若給
    night 且該日有夜盤,再加第 5 維(夜盤報酬),並只保留有夜盤的日。"""
    us = {s: _overnight_ret(raw[s]) for s in US_SYMBOLS}
    us_dates = sorted(us[US_SYMBOLS[0]])

    def prior(twdate, sym):
        i = bisect.bisect_left(us_dates, twdate) - 1
        return us[sym].get(us_dates[i]) if i >= 0 else None

    use_night = bool(night)
    feats = US_SYMBOLS + (["夜盤"] if use_night else [])
    tw = raw[TWII]
    twd = [r["date"] for r in tw]
    twc = [r["close"] for r in tw]
    two = [r["open"] for r in tw]
    rows = []
    for i in range(1, len(twd)):
        T = twd[i]
        feat = [prior(T, s) for s in US_SYMBOLS]
        if any(x is None for x in feat) or twc[i - 1] <= 0:
            continue
        if use_night:
            nv = night.get(T)
            if nv is None:
                continue
            feat = feat + [nv]
        cc = (twc[i] / twc[i - 1] - 1) * 100
        gap = (two[i] / twc[i - 1] - 1) * 100 if two[i] else None
        rows.append((T, feat, cc, gap))
    return rows, feats


# ── 模型 ────────────────────────────────────────────────
def _fit_predict(Xtr, ytr, x):
    A = np.c_[np.ones(len(Xtr)), Xtr]
    beta, *_ = np.linalg.lstsq(A, ytr, rcond=None)
    resid = ytr - A @ beta
    return float(np.r_[1, x] @ beta), resid


def _band(pred, resid, ref_level):
    """校準信心帶(訓練殘差經驗分位數)。ref_level 給點數換算。"""
    q = {p: float(np.percentile(resid, p)) for p in (10, 25, 75, 90)}
    up = float(np.mean((pred + resid) > 0)) * 100

    def pt(v):
        return round(v / 100 * ref_level)

    return {"p10": round(pred + q[10], 2), "p25": round(pred + q[25], 2),
            "p75": round(pred + q[75], 2), "p90": round(pred + q[90], 2),
            "p10_pt": pt(pred + q[10]), "p25_pt": pt(pred + q[25]),
            "p75_pt": pt(pred + q[75]), "p90_pt": pt(pred + q[90]),
            "up_prob": round(up, 0)}


def predict_next(raw: dict | None = None, night: dict | None = None,
                 window: int = WINDOW) -> dict:
    raw = raw or _fetch_raw()
    us = {s: _overnight_ret(raw[s]) for s in US_SYMBOLS}
    latest_us = max(us[US_SYMBOLS[0]])
    x_us = [us[s].get(latest_us) for s in US_SYMBOLS]
    if any(v is None for v in x_us):
        return {"error": "最新隔夜美股資料缺"}
    tw = raw[TWII]
    ref_level = tw[-1]["close"]          # 最新加權收盤 → %換點數
    last_twii_date = tw[-1]["date"]
    # 夜盤:目標日(下一交易日)的夜盤 = 掛在目標日的 after_market。若 FinMind
    # 已更新(最新夜盤日 > 最新現貨日)→ 用 5 特徵,否則退回美股 4 項。
    use_night = False
    night_val = None
    if night:
        nmax = max(night)
        if nmax > last_twii_date:
            night_val = night[nmax]
            use_night = True
    rows, feats = build_dataset(raw, night if use_night else None)
    if len(rows) < window + 10:
        # 夜盤共同樣本不足 → 退回美股
        rows, feats = build_dataset(raw, None)
        use_night = False
        night_val = None
    x = list(x_us) + ([night_val] if use_night else [])
    tr = rows[-window:]
    Xtr = np.array([r[1] for r in tr], dtype=float)
    out = {"latest_us_date": latest_us, "asof_twii_date": last_twii_date,
           "ref_level": round(ref_level, 2), "use_night": use_night,
           "n_train": len(tr), "features": feats,
           "us_overnight": {s: round(us[s][latest_us], 2) for s in US_SYMBOLS}}
    if use_night:
        out["night_ret"] = round(night_val, 2)
    for tgt, key in ((2, "cc"), (3, "gap")):
        y = np.array([r[tgt] for r in tr], dtype=float)
        m = ~np.isnan(y)
        if m.sum() < 40:
            continue
        pred, resid = _fit_predict(Xtr[m], y[m], np.array(x))
        out[key] = {"pred": round(pred, 2),
                    "pred_pt": round(pred / 100 * ref_level),
                    **_band(pred, resid, ref_level)}
    return out


def backtest(raw: dict | None = None, night: dict | None = None,
             window: int = WINDOW) -> dict:
    raw = raw or _fetch_raw()
    rows, feats = build_dataset(raw, night)
    res = {"n_days": len(rows), "window": window, "features": feats,
           "use_night": bool(night)}
    for tgt, key in ((2, "cc"), (3, "gap")):
        preds, acts, cov25, cov10 = [], [], [], []
        for j in range(window, len(rows)):
            tr = rows[j - window:j]
            Xtr = np.array([r[1] for r in tr], dtype=float)
            y = np.array([r[tgt] for r in tr], dtype=float)
            m = ~np.isnan(y)
            if m.sum() < 40:
                continue
            act = rows[j][tgt]
            if act is None or np.isnan(act):
                continue
            pred, resid = _fit_predict(Xtr[m], y[m], np.array(rows[j][1]))
            b = _band(pred, resid, 1.0)
            preds.append(pred); acts.append(act)
            cov25.append(1 if b["p25"] <= act <= b["p75"] else 0)
            cov10.append(1 if b["p10"] <= act <= b["p90"] else 0)
        P, A = np.array(preds), np.array(acts)
        if not len(A):
            continue
        conf = np.abs(P) > np.median(np.abs(P))
        mae_a = np.mean(np.abs(A - P)); mae_0 = np.mean(np.abs(A))
        res[key] = {
            "n": len(A), "base_up_pct": round(np.mean(A > 0) * 100, 1),
            "dir_hit_pct": round(np.mean((P > 0) == (A > 0)) * 100, 1),
            "dir_hit_conf_pct": round(np.mean((P[conf] > 0) == (A[conf] > 0)) * 100, 1),
            "skill_vs_zero_pct": round((mae_0 - mae_a) / mae_0 * 100, 1),
            "corr": round(float(np.corrcoef(P, A)[0, 1]), 2),
            "cover_2575_pct": round(np.mean(cov25) * 100, 1),
            "cover_1090_pct": round(np.mean(cov10) * 100, 1),
        }
    return res


# ── 呈現 ────────────────────────────────────────────────
def _arrow(v):
    return "▲ 偏多" if v > 0.15 else ("▼ 偏空" if v < -0.15 else "→ 持平")


def _line(p, label):
    return (f"{label} {p['pred']:+.2f}% ({p['pred_pt']:+d}點)  {_arrow(p['pred'])}"
            f"(上漲機率 {p['up_prob']:.0f}%)\n"
            f"  區間 25-75%: [{p['p25']:+.2f}, {p['p75']:+.2f}]% "
            f"([{p['p25_pt']:+d}, {p['p75_pt']:+d}]點)"
            f"｜10-90%: [{p['p10']:+.2f}, {p['p90']:+.2f}]%")


def format_report(pred):
    if pred.get("error"):
        return f"明天大盤預期: {pred['error']}"
    on = pred["us_overnight"]
    d = pred["latest_us_date"]
    src = "美股+台指期夜盤" if pred.get("use_night") else "美股(夜盤資料未更新)"
    lines = [
        f"🌏 明天大盤預期({src} → 加權指數)",
        f"加權現值 {pred['ref_level']:.0f}",
        f"隔夜美股({d[:4]}/{d[4:6]}/{d[6:]}): 費半{on['^SOX']:+.2f}%"
        f" 那指{on['^IXIC']:+.2f}% 標普{on['^GSPC']:+.2f}% 台積ADR{on['TSM']:+.2f}%",
    ]
    if pred.get("use_night"):
        lines.append(f"台指期夜盤: {pred['night_ret']:+.2f}%(含美股收盤後+亞洲+台灣新聞)")
    lines.append("━━━━━━━━━━━━")
    if "gap" in pred:
        lines.append(_line(pred["gap"], "預期開盤跳空"))
    if "cc" in pred:
        lines.append(_line(pred["cc"], "預期收盤(收-收)"))
    lines.append("\n⚠ 只預測大盤(回測跳空87%/收-收76%)。個股僅供背景風向,"
                 "個股自身方向不在此保證。非買賣訊號。")
    return "\n".join(lines)


def render_html(pred, bt=None):
    import html as _h
    nav = __import__("site_nav").nav_html("/market-tomorrow")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:840px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:14px 18px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  .big{font-size:1.6em;font-weight:700;} .up{color:#c0392b;} .dn{color:#0a8a3a;} .flat{color:#888;}
  table{width:100%;border-collapse:collapse;font-size:.9em;} td,th{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;}
  th:first-child,td:first-child{text-align:left;} .small{font-size:.85em;color:#666;}
  .note{background:#eef5ff;border:1px solid #cfe0f5;border-radius:6px;padding:10px 14px;font-size:.88em;line-height:1.6;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>明天大盤預期</title>{css}</head><body>{nav}'
            f'<h1>🌏 明天大盤預期</h1>')
    if pred.get("error"):
        return head + f'<section>⚠ {_h.escape(str(pred["error"]))}</section></body></html>'
    d = pred["latest_us_date"]; on = pred["us_overnight"]

    def _cls(v):
        return "up" if v > 0.15 else ("dn" if v < -0.15 else "flat")

    def _blk(key, label):
        if key not in pred:
            return ""
        p = pred[key]
        return (f'<section><h3>{label}</h3>'
                f'<div class="big {_cls(p["pred"])}">{p["pred"]:+.2f}% '
                f'({p["pred_pt"]:+d} 點)</div>'
                f'<div>{_arrow(p["pred"])}｜上漲機率 <b>{p["up_prob"]:.0f}%</b></div>'
                f'<div class="small">25-75% 區間 [{p["p25"]:+.2f}, {p["p75"]:+.2f}]% '
                f'([{p["p25_pt"]:+d}, {p["p75_pt"]:+d}] 點)'
                f'｜10-90% [{p["p10"]:+.2f}, {p["p90"]:+.2f}]%</div></section>')

    src = "美股 + 台指期夜盤" if pred.get("use_night") else "美股(夜盤資料未更新,退回美股 4 項)"
    night = (f'｜台指期夜盤 <span class="{_cls(pred["night_ret"])}">'
             f'{pred["night_ret"]:+.2f}%</span>' if pred.get("use_night") else "")
    body = (f'<section><b>加權現值 {pred["ref_level"]:.0f}</b>｜訊號源:{src}<br>'
            f'<b>隔夜</b>({d[:4]}/{d[4:6]}/{d[6:]}): '
            f'費半 <span class="{_cls(on["^SOX"])}">{on["^SOX"]:+.2f}%</span>'
            f'｜那指 <span class="{_cls(on["^IXIC"])}">{on["^IXIC"]:+.2f}%</span>'
            f'｜標普 <span class="{_cls(on["^GSPC"])}">{on["^GSPC"]:+.2f}%</span>'
            f'｜台積ADR <span class="{_cls(on["TSM"])}">{on["TSM"]:+.2f}%</span>'
            f'{night}</section>'
            + _blk("gap", "預期開盤跳空") + _blk("cc", "預期收盤(收-收)"))
    if bt:
        rowsh = ""
        for key, lab in (("gap", "開盤跳空"), ("cc", "收盤收-收")):
            s = bt.get(key)
            if s:
                rowsh += (f'<tr><td>{lab}</td><td>{s["dir_hit_pct"]}%</td>'
                          f'<td>{s["dir_hit_conf_pct"]}%</td><td>{s["skill_vs_zero_pct"]:+.1f}%</td>'
                          f'<td>{s["cover_2575_pct"]}%</td></tr>')
        body += (f'<section><h3>回測成效(walk-forward, {bt["n_days"]} 交易日,'
                 f'{"含夜盤" if bt.get("use_night") else "美股"})</h3>'
                 '<table><thead><tr><th>目標</th><th>方向命中</th><th>高信心</th>'
                 '<th>skill</th><th>25-75%覆蓋</th></tr></thead><tbody>'
                 + rowsh + '</tbody></table>'
                 '<p class="small">方向命中=預測漲跌方向對的比例;skill=比「猜0%」少的誤差;'
                 '25-75%覆蓋應接近50%(校準好)。</p></section>')
    body += ('<section class="note">📖 <b>方法</b>:隔夜美股(費半/那指/標普/台積ADR)'
             '+ <b>台指期夜盤</b>(15:00→05:00,把美股收盤後、亞洲時段、台灣本地的'
             '新聞/事件都定價進去)滾動 OLS(前120日)→ 隔天加權指數方向與區間。'
             '信心帶用訓練殘差經驗分位數(校準)。夜盤資料未更新時自動退回美股 4 項。'
             '<br>⚠ <b>只預測大盤</b>:個股每日漲跌以自身雜訊為主,隔夜市場成分蓋不過,'
             '個股方向不在此保證,僅供背景風向。非買賣訊號。</section>')
    return head + body + '</body></html>'


def _push(report, recipients):
    import line_push
    tok = line_push.resolve_token()
    for r in recipients:
        ok = line_push.push_text(report, tok, r)
        print(f"[line] → {r[:8]}…: {'✅' if ok else '❌'}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--line-to", help="LINE 推播收件人(逗號分隔)")
    ap.add_argument("--no-night", action="store_true", help="不用台指期夜盤(只美股)")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    raw = _fetch_raw(max_age_h=0 if args.line_to else 6.0)
    if not all(raw.get(s) for s in US_SYMBOLS + [TWII]):
        print("資料抓取失敗", file=sys.stderr)
        sys.exit(1)
    night = {} if args.no_night else fetch_night_returns(
        max_age_h=0 if args.line_to else 6.0)

    if args.backtest:
        r = backtest(raw, night or None, args.window)
        tag = "美股+夜盤" if r.get("use_night") else "美股4項"
        print(f"\n明天大盤預期 回測(walk-forward, {tag}, window={r['window']}, "
              f"{r['n_days']} 交易日)")
        for key, lab in (("gap", "開盤跳空"), ("cc", "收盤(收-收)")):
            s = r.get(key)
            if not s:
                continue
            print(f"\n【{lab}】n={s['n']}  base rate(漲) {s['base_up_pct']}%")
            print(f"  方向命中 {s['dir_hit_pct']}% (高信心 {s['dir_hit_conf_pct']}%)"
                  f"  skill {s['skill_vs_zero_pct']:+.1f}%  corr {s['corr']:+.2f}")
            print(f"  信心帶 25-75%: {s['cover_2575_pct']}%(目標50)"
                  f"  10-90%: {s['cover_1090_pct']}%(目標80)")
        out = r
    else:
        out = predict_next(raw, night or None, args.window)
        report = format_report(out)
        print(report)
        if args.line_to:
            _push(report, [x for x in args.line_to.split(",") if x.strip()])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n→ 已存 {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()

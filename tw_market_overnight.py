#!/usr/bin/env python3
"""明天大盤預期 (tw_market_overnight)

用「隔夜美股」預測隔天台股加權指數(TAIEX)的方向/幅度/區間。
prediction 當下(美股收盤後~隔天開盤前)可得的訊號:
  ^SOX 費半、^IXIC 那斯達克、^GSPC 標普、TSM 台積電 ADR 的隔夜報酬。
滾動 OLS(前 W 日)→ 預測隔天 TAIEX 收-收 與 開盤跳空,附校準信心帶。

⚠ 只預測「大盤」——回測 walk-forward:收-收方向 72%、跳空 81%、skill
  +14~20%(見 --backtest)。個股方向救不了(市場成分被個股雜訊蓋過),
  故本工具刻意只做指數;個股請把此當「背景風向」。

資料源:Yahoo Finance(concept_momentum/data_fetcher.fetch_yahoo)。
用法:
  tw_market_overnight.py                 # 明天大盤預期
  tw_market_overnight.py --backtest      # walk-forward 回測
  tw_market_overnight.py --json-out o.json
"""
from __future__ import annotations
import argparse
import bisect
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
RAW_CACHE = os.path.join(CACHE, "overnight_us.json")
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

# 隔夜特徵(美股/ADR 代號)+ 目標指數
US_SYMBOLS = ["^SOX", "^IXIC", "^GSPC", "TSM"]
TWII = "^TWII"
WINDOW = 120                 # 滾動擬合視窗(交易日)


# ── 資料 ────────────────────────────────────────────────
def _fetch_raw(rng: str = "2y", max_age_h: float = 6.0) -> dict:
    """抓/快取 Yahoo 日線(US 隔夜 + TWII)。快取新鮮則直接用。"""
    if os.path.exists(RAW_CACHE):
        age = (time.time() - os.path.getmtime(RAW_CACHE)) / 3600
        if age < max_age_h:
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


def _overnight_ret(rows: list[dict]) -> dict:
    """美股日線 → {date: 隔夜報酬%(close/prev_close-1)}。"""
    d = [r["date"] for r in rows]
    c = [r["close"] for r in rows]
    return {d[i]: (c[i] / c[i - 1] - 1) * 100
            for i in range(1, len(d)) if c[i - 1] > 0}


def build_dataset(raw: dict) -> tuple[list, list[str]]:
    """→ ([(twdate, feat[4], cc, gap)], 特徵名)。feat = 該台股日之前最近一
    次美股隔夜報酬(SOX/IXIC/GSPC/TSM)。cc=收-收%、gap=前收→開%。"""
    us = {s: _overnight_ret(raw[s]) for s in US_SYMBOLS}
    us_dates = sorted(us[US_SYMBOLS[0]])

    def prior(twdate, sym):
        i = bisect.bisect_left(us_dates, twdate) - 1
        return us[sym].get(us_dates[i]) if i >= 0 else None

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
        cc = (twc[i] / twc[i - 1] - 1) * 100
        gap = (two[i] / twc[i - 1] - 1) * 100 if two[i] else None
        rows.append((T, feat, cc, gap))
    return rows, US_SYMBOLS


# ── 模型:滾動 OLS ──────────────────────────────────────
def _fit_predict(Xtr: np.ndarray, ytr: np.ndarray, x: np.ndarray):
    """OLS 擬合 → (預測值, 訓練殘差)。含截距。"""
    A = np.c_[np.ones(len(Xtr)), Xtr]
    beta, *_ = np.linalg.lstsq(A, ytr, rcond=None)
    resid = ytr - A @ beta
    pred = float(np.r_[1, x] @ beta)
    return pred, resid


def _calibrated_band(pred: float, resid: np.ndarray) -> dict:
    """用訓練殘差的經驗分位數 → 校準信心帶(非常態假設)。"""
    q = {p: float(np.percentile(resid, p)) for p in (10, 25, 75, 90)}
    up_prob = float(np.mean((pred + resid) > 0)) * 100
    return {
        "p10": round(pred + q[10], 2), "p25": round(pred + q[25], 2),
        "p75": round(pred + q[75], 2), "p90": round(pred + q[90], 2),
        "up_prob": round(up_prob, 0),
    }


def predict_next(raw: dict | None = None, window: int = WINDOW) -> dict:
    """用「全部歷史 + 最新隔夜」預測下一個台股交易日。"""
    raw = raw or _fetch_raw()
    rows, _ = build_dataset(raw)
    if len(rows) < window + 10:
        return {"error": "資料不足"}
    # 最新一列的特徵 = 最近一次已知隔夜(對應「下一台股日」)
    # 但 rows 末列的 T 已是最後有 TWII 的日;要預測「再下一日」需用最新
    # 美股隔夜。用最後 window 列擬合,x = 最新美股隔夜向量。
    us = {s: _overnight_ret(raw[s]) for s in US_SYMBOLS}
    latest_us_date = max(us[US_SYMBOLS[0]])
    x = np.array([us[s].get(latest_us_date) for s in US_SYMBOLS], dtype=float)
    if np.any(np.isnan(x)):
        return {"error": "最新隔夜資料缺"}
    tr = rows[-window:]
    Xtr = np.array([r[1] for r in tr], dtype=float)
    out = {"latest_us_date": latest_us_date,
           "us_overnight": {s: round(us[s][latest_us_date], 2) for s in US_SYMBOLS},
           "asof_twii_date": rows[-1][0], "n_train": len(tr)}
    for tgt, key in ((2, "cc"), (3, "gap")):
        y = np.array([r[tgt] for r in tr], dtype=float)
        m = ~np.isnan(y)
        if m.sum() < 40:
            continue
        pred, resid = _fit_predict(Xtr[m], y[m], x)
        band = _calibrated_band(pred, resid)
        out[key] = {"pred": round(pred, 2), **band}
    return out


# ── 回測(walk-forward)──────────────────────────────────
def backtest(raw: dict | None = None, window: int = WINDOW) -> dict:
    raw = raw or _fetch_raw()
    rows, _ = build_dataset(raw)
    res = {"n_days": len(rows), "window": window}
    for tgt, key in ((2, "cc"), (3, "gap")):
        preds, acts, sox, covers25, covers10 = [], [], [], [], []
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
            band = _calibrated_band(pred, resid)
            preds.append(pred); acts.append(act); sox.append(rows[j][1][0])
            covers25.append(1 if band["p25"] <= act <= band["p75"] else 0)
            covers10.append(1 if band["p10"] <= act <= band["p90"] else 0)
        P, A, S = np.array(preds), np.array(acts), np.array(sox)
        if not len(A):
            continue
        dir_hit = np.mean((P > 0) == (A > 0)) * 100
        dir_sox = np.mean((S > 0) == (A > 0)) * 100
        mae_a = np.mean(np.abs(A - P)); mae_0 = np.mean(np.abs(A))
        conf = np.abs(P) > np.median(np.abs(P))
        res[key] = {
            "n": len(A), "base_up_pct": round(np.mean(A > 0) * 100, 1),
            "dir_hit_pct": round(dir_hit, 1),
            "dir_hit_conf_pct": round(np.mean((P[conf] > 0) == (A[conf] > 0)) * 100, 1),
            "dir_sox_only_pct": round(dir_sox, 1),
            "skill_vs_zero_pct": round((mae_0 - mae_a) / mae_0 * 100, 1),
            "corr": round(float(np.corrcoef(P, A)[0, 1]), 2),
            "cover_2575_pct": round(np.mean(covers25) * 100, 1),
            "cover_1090_pct": round(np.mean(covers10) * 100, 1),
        }
    return res


# ── 呈現 ────────────────────────────────────────────────
def _arrow(v: float) -> str:
    return "▲ 偏多" if v > 0.15 else ("▼ 偏空" if v < -0.15 else "→ 持平")


def format_report(pred: dict) -> str:
    if pred.get("error"):
        return f"明天大盤預期: {pred['error']}"
    on = pred["us_overnight"]
    lines = [
        "🌏 明天大盤預期(隔夜美股 → 加權指數)",
        f"隔夜({pred['latest_us_date'][:4]}/{pred['latest_us_date'][4:6]}/{pred['latest_us_date'][6:]}):"
        f" 費半{on['^SOX']:+.2f}% 那指{on['^IXIC']:+.2f}%"
        f" 標普{on['^GSPC']:+.2f}% 台積ADR{on['TSM']:+.2f}%",
        "━━━━━━━━━━━━",
    ]
    if "gap" in pred:
        g = pred["gap"]
        lines.append(f"預期開盤跳空 {g['pred']:+.2f}%  {_arrow(g['pred'])}"
                     f"(上漲機率 {g['up_prob']:.0f}%)")
        lines.append(f"  區間 25-75%: [{g['p25']:+.2f}, {g['p75']:+.2f}]%"
                     f"｜10-90%: [{g['p10']:+.2f}, {g['p90']:+.2f}]%")
    if "cc" in pred:
        c = pred["cc"]
        lines.append(f"預期收盤(收-收) {c['pred']:+.2f}%  {_arrow(c['pred'])}"
                     f"(上漲機率 {c['up_prob']:.0f}%)")
        lines.append(f"  區間 25-75%: [{c['p25']:+.2f}, {c['p75']:+.2f}]%"
                     f"｜10-90%: [{c['p10']:+.2f}, {c['p90']:+.2f}]%")
    lines.append("\n⚠ 只預測大盤方向(回測跳空81%/收-收72%)。個股僅供背景風向,"
                 "個股自身方向不在此保證。非買賣訊號。")
    return "\n".join(lines)


def render_html(pred: dict, bt: dict | None = None) -> str:
    import html as _h
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/lin-matrix">📐 林則行矩陣</a> '
           '<a href="/stock-futures">🔥 個股期火熱</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:820px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:14px 18px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  .big{font-size:1.6em;font-weight:700;} .up{color:#c0392b;} .dn{color:#0a8a3a;} .flat{color:#888;}
  .bar{height:14px;border-radius:7px;background:linear-gradient(90deg,#0a8a3a,#ddd,#c0392b);position:relative;margin:6px 0;}
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
    d = pred["latest_us_date"]
    on = pred["us_overnight"]

    def _cls(v):
        return "up" if v > 0.15 else ("dn" if v < -0.15 else "flat")

    def _blk(key, label):
        if key not in pred:
            return ""
        p = pred[key]
        return (f'<section><h3>{label}</h3>'
                f'<div class="big {_cls(p["pred"])}">{p["pred"]:+.2f}%</div>'
                f'<div>{_arrow(p["pred"])}｜上漲機率 <b>{p["up_prob"]:.0f}%</b></div>'
                f'<div class="small">25-75% 區間 [{p["p25"]:+.2f}, {p["p75"]:+.2f}]%'
                f'｜10-90% [{p["p10"]:+.2f}, {p["p90"]:+.2f}]%</div></section>')

    body = (f'<section><b>隔夜美股</b>({d[:4]}/{d[4:6]}/{d[6:]}):'
            f' 費半 <span class="{_cls(on["^SOX"])}">{on["^SOX"]:+.2f}%</span>'
            f'｜那指 <span class="{_cls(on["^IXIC"])}">{on["^IXIC"]:+.2f}%</span>'
            f'｜標普 <span class="{_cls(on["^GSPC"])}">{on["^GSPC"]:+.2f}%</span>'
            f'｜台積ADR <span class="{_cls(on["TSM"])}">{on["TSM"]:+.2f}%</span></section>'
            + _blk("gap", "預期開盤跳空") + _blk("cc", "預期收盤(收-收)"))
    if bt:
        rows = ""
        for key, lab in (("gap", "開盤跳空"), ("cc", "收盤收-收")):
            s = bt.get(key)
            if s:
                rows += (f'<tr><td>{lab}</td><td>{s["dir_hit_pct"]}%</td>'
                         f'<td>{s["dir_hit_conf_pct"]}%</td><td>{s["skill_vs_zero_pct"]:+.1f}%</td>'
                         f'<td>{s["cover_2575_pct"]}%</td></tr>')
        body += (f'<section><h3>回測成效(walk-forward, {bt["n_days"]} 交易日)</h3>'
                 '<table><thead><tr><th>目標</th><th>方向命中</th><th>高信心</th>'
                 '<th>skill</th><th>25-75%覆蓋</th></tr></thead><tbody>'
                 + rows + '</tbody></table>'
                 '<p class="small">方向命中=預測漲跌方向對的比例;skill=比「猜0%」少的誤差;'
                 '25-75%覆蓋應接近50%(校準好)。</p></section>')
    body += ('<section class="note">📖 <b>方法</b>:隔夜美股(費半/那指/標普/台積ADR)'
             '滾動 OLS(前120日)→ 隔天加權指數方向與區間。信心帶用訓練殘差經驗分位數'
             '(校準,非過度自信)。<br>⚠ <b>只預測大盤</b>:個股每日漲跌以自身雜訊為主,'
             '隔夜市場成分蓋不過,故個股方向不在此保證,僅供背景風向。非買賣訊號。</section>')
    return head + body + '</body></html>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--json-out")
    args = ap.parse_args()
    raw = _fetch_raw()
    if not all(raw.get(s) for s in US_SYMBOLS + [TWII]):
        print("資料抓取失敗", file=sys.stderr)
        sys.exit(1)
    if args.backtest:
        r = backtest(raw, args.window)
        print(f"\n明天大盤預期 回測(walk-forward, window={r['window']}, "
              f"{r['n_days']} 交易日)")
        for key, lab in (("gap", "開盤跳空"), ("cc", "收盤(收-收)")):
            s = r.get(key)
            if not s:
                continue
            print(f"\n【{lab}】n={s['n']}  base rate(漲) {s['base_up_pct']}%")
            print(f"  方向命中 {s['dir_hit_pct']}% (高信心子集 {s['dir_hit_conf_pct']}%,"
                  f" 純SOX符號 {s['dir_sox_only_pct']}%)")
            print(f"  skill vs猜0 {s['skill_vs_zero_pct']:+.1f}%  corr {s['corr']:+.2f}")
            print(f"  信心帶校準 25-75%: {s['cover_2575_pct']}%(目標50)"
                  f"  10-90%: {s['cover_1090_pct']}%(目標80)")
        out = r
    else:
        out = predict_next(raw, args.window)
        print(format_report(out))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n→ 已存 {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()

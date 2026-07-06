#!/usr/bin/env python3
"""轉機接力 Layer 1 回測 — 事件研究 (point-in-time)。

Layer 1 四濾網 import 正式篩選器的純函數，逐日 as-of 重建：
  A 毛利率  : TaiwanStockFinancialStatements，季報可用日=法定死線 (見下表)
  B 量能    : v2 價格面板 rows[:i+1] (未還原 close/volume，與正式版 Yahoo 同口徑)
  D 季線    : 同上
  C 借券賣出: TaiwanDailyShortSaleBalances as-of 截斷
Layer 2 overlay：A/B/D 三訊號 (C 分點無公開歷史，誠實跳過) 以盤前 anchor 語意
在每個 Layer 1 事件日評分，比較 abd>=2 與 <2 兩組的前向表現 → 回答
「Layer 2 有沒有在 Layer 1 之上加值」。

進場：訊號日隔日還原開盤 (07:30 盤前推播 → 當日開盤可成交)。
成本/CI/基準：backtest_lib (同第二波 v2)。

季報可用日: 3/31→5/15, 6/30→8/14, 9/30→11/14, 12/31→翌年3/31 (保守)。

偏差說明（相較 brief 參考碼，controller 授權的硬化）：
  D1. 不快取空回應：fetch_fs/fetch_sbl 拿到空 data 時直接 return []，不寫 cache 檔，
      避免 HTTP 402 quota ban 把空結果污染快取 7-30 天。
  D2. 速率限制 + 停火偵測：每次未命中快取的 _fm 呼叫後 sleep(0.03)；
      追蹤 fetch_fs 連續空回應數，≥100 → 印 ABORT 訊息並 sys.exit(3)。
  D3. 建議用 nohup 背景執行（首跑 ~1-2 小時），快取使重跑可恢復。
"""
import argparse
import bisect
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                            # noqa: E402
from backtest_prices import load_panel, BT_CACHE, _token, _fm        # noqa: E402
from tw_turnaround_screener import (TR_DEFAULTS, margin_passes,      # noqa: E402
                                    volume_passes, ma60_passes, short_passes)
from tw_limitup_signal import (signal_a_relay, signal_b_short_cover,  # noqa: E402
                               signal_d_volume)


def _avail(qend: str) -> str:
    """季末日 YYYY-MM-DD → 可用日 YYYYMMDD (法定申報死線)。
    3/31→5/15, 6/30→8/14, 9/30→11/14, 12/31→翌年3/31
    保守規則：多數公司提早公告，此規則低估可實現 edge，不會高估。
    """
    y, m = int(qend[:4]), int(qend[5:7])
    return {3: f"{y}0515", 6: f"{y}0814", 9: f"{y}1114", 12: f"{y+1}0331"}[m]


def fetch_fs(code: str, token: str) -> list[dict]:
    """季毛利率 + 可用日。快取 30 天（僅在有資料時寫入，空資料不快取）。
    回 [{date, avail, gross_margin}] 升冪。

    D1 偏差：data 為空時直接 return []，不寫 cache 檔——避免 HTTP 402 quota ban
    把空結果快取 30 天，等同永久跳過該股。
    """
    p = os.path.join(BT_CACHE, f"fs_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 30 * 86400:
        return json.load(open(p))
    data = _fm("TaiwanStockFinancialStatements", code, "2023-07-01", token)
    time.sleep(0.03)  # D2: 速率限制
    if not data:
        return []  # D1: 不快取空回應
    byq = {}
    for r in data:
        if r.get("date") and r.get("type") in ("Revenue", "GrossProfit"):
            byq.setdefault(r["date"], {})[r["type"]] = r.get("value")
    out = []
    for d in sorted(byq):
        q = byq[d]
        rev, gp = q.get("Revenue"), q.get("GrossProfit")
        if rev and gp is not None and rev > 0:
            out.append({"date": d, "avail": _avail(d),
                        "gross_margin": gp / rev * 100})
    if not out:
        return []  # D1: 有 raw data 但解析後為空也不快取
    json.dump(out, open(p, "w"))
    return out


def fetch_sbl(code: str, token: str) -> list[dict]:
    """借券賣出+融券餘額全歷史。快取 7 天（僅在有資料時寫入，空資料不快取）。
    回 short_passes 相容格式 (張)。

    D1 偏差：data 為空時直接 return []，不寫 cache 檔。
    """
    p = os.path.join(BT_CACHE, f"sbl_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        return json.load(open(p))
    data = _fm("TaiwanDailyShortSaleBalances", code, "2024-10-01", token)
    time.sleep(0.03)  # D2: 速率限制
    if not data:
        return []  # D1: 不快取空回應
    out = []
    for r in data:
        d = r.get("date")
        if not d:
            continue
        sbl = (r.get("SBLShortSalesCurrentDayBalance") or 0) / 1000
        mgn = (r.get("MarginShortSalesCurrentDayBalance") or 0) / 1000
        out.append({"date": d.replace("-", ""), "balance": sbl,
                    "sbl": sbl, "margin": mgn})
    out.sort(key=lambda x: x["date"])
    if not out:
        return []  # D1: 解析後空也不快取
    json.dump(out, open(p, "w"))
    return out


def run(horizons, cost, start="2025-01-01", entry="next_open"):
    token = _token()
    panel = load_panel(start)
    p = argparse.Namespace(**TR_DEFAULTS)
    max_h = max(horizons)
    events = []            # (code, date, i, abd_score)
    n_gm_pass_stocks = 0
    consecutive_empty_fs = 0  # D2: 連續空 FS 計數

    codes = sorted(panel.stocks)
    for n_done, code in enumerate(codes):
        if (n_done + 1) % 200 == 0:
            print(f"  {n_done+1}/{len(codes)} events={len(events)}", file=sys.stderr)
        fs = fetch_fs(code, token)
        if not fs:
            # D2: 追蹤連續空 FS 回應
            consecutive_empty_fs += 1
            if consecutive_empty_fs >= 100:
                print(
                    "\n[ABORT] 連續 100 檔 FS 空回應 — 疑似 FinMind quota ban，"
                    "稍後重跑 (已抓部分已快取)",
                    file=sys.stderr
                )
                sys.exit(3)
            continue
        consecutive_empty_fs = 0  # 有資料就重置計數
        avails = [q["avail"] for q in fs]
        # 快篩：任一時點的「最近 4 季」有沒有可能過 A — 全期間都不過就跳過
        ever = False
        for k in range(4, len(fs) + 1):
            ok, _ = margin_passes(fs[k - 4:k], p.gm_pp, p.gm_qoq)
            if ok:
                ever = True
                break
        if not ever:
            continue
        n_gm_pass_stocks += 1
        sbl = fetch_sbl(code, token)
        sbl_dates = [r["date"] for r in sbl]
        rows = panel.stocks[code]["rows"]
        fires, scores = [], {}
        for i in range(70, len(rows) - max_h):
            t = rows[i]["date"]
            navail = bisect.bisect_right(avails, t)
            pit = fs[:navail][-4:]
            ok_a, _ = margin_passes(pit, p.gm_pp, p.gm_qoq)
            if not ok_a:
                continue
            ok_b, _ = volume_passes(rows[:i + 1], p.vol_ratio)
            if not ok_b:
                continue
            ok_d, _ = ma60_passes(rows[:i + 1], accel_days=p.ma_accel_days,
                                  curvature_min_ratio=p.ma_curv_ratio)
            if not ok_d:
                continue
            nsbl = bisect.bisect_right(sbl_dates, t)
            ok_c, _ = short_passes(sbl[:nsbl], p.sbl_decline)
            if not ok_c:
                continue
            fires.append(i)
            # Layer 2 overlay: A/B/D 盤前語意 (anchor = 已收盤 K 棒數)
            # C 訊號使用分點資料（無公開歷史），誠實跳過
            a_ok, _ = signal_a_relay(rows[:i + 1], anchor=i + 1)
            b_ok, _ = signal_b_short_cover(sbl[:nsbl])
            d_ok, _ = signal_d_volume(rows[:i + 1], anchor=i + 1)
            scores[i] = int(a_ok) + int(b_ok) + int(d_ok)
        for i in bl.dedup_cooldown(fires, max_h):
            events.append((code, rows[i]["date"], i, scores[i]))

    print(f"\nGM 可能過關股數 {n_gm_pass_stocks} / {len(codes)}；"
          f"episodes {len(events)}", file=sys.stderr)
    result = {"n_episodes": len(events), "n_stocks_gm_pass": n_gm_pass_stocks,
              "entry": entry, "cost": cost, "horizons": {}, "layer2": {}}
    for h in horizons:
        absr, excr, edges = [], [], []
        grp = {"ge2": {"abs": [], "exc": []}, "lt2": {"abs": [], "exc": []}}
        by_year = {}
        for code, date, _i, sc in events:
            r = panel.fwd(code, date, h, entry)
            if r is None:
                continue
            sr, tr = r
            absr.append(sr); excr.append(sr - tr)
            by_year.setdefault(date[:4], []).append(sr - tr)
            b = panel.matched_baseline(date, h, entry=entry)
            if b is not None:
                edges.append(sr - tr - b)
            g = grp["ge2" if sc >= 2 else "lt2"]
            g["abs"].append(sr); g["exc"].append(sr - tr)
        s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
        s["per_year"] = {y: {"n": len(v), "exc_mean": round(sum(v)/len(v), 2),
                             "exc_ci": [round(x, 2) for x in bl.bootstrap_ci(v)]}
                         for y, v in sorted(by_year.items())}
        result["horizons"][h] = s
        result["layer2"][h] = {k: bl.summarize_events(v["abs"], v["exc"], cost)
                               for k, v in grp.items()}
        if s.get("n"):
            print(f"\n【H={h}d】n={s['n']} 超額 {s['exc_mean']:+.2f}% "
                  f"CI {s['exc_ci']} t={s['t']} 淨 {s['net']:+.2f}% "
                  f"edge {s.get('edge_mean')}")
            for k, lab in (("ge2", "ABD≥2"), ("lt2", "ABD<2")):
                g = result["layer2"][h][k]
                if g.get("n"):
                    print(f"    {lab}: n={g['n']} 超額 {g['exc_mean']:+.2f}% "
                          f"CI {g['exc_ci']}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="轉機接力 Layer 1 回測 (point-in-time 事件研究)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--entry", default="next_open",
                    choices=["next_open", "signal_close"])
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    r = run(args.horizon, args.cost, start=args.start, entry=args.entry)
    if args.json_out:
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "params": {"horizons": args.horizon, "cost": args.cost,
                              "entry": args.entry, **TR_DEFAULTS},
                   "result": r},
                  open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[json] 寫入 {args.json_out}", file=sys.stderr)

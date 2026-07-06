#!/usr/bin/env python3
"""借券雷達 + 空頭撤退 回測 — 事件研究 (point-in-time)。

兩個盤後推播策略的歷史驗證 (live 規則見 tw_lending_monitor.py)：
  空頭撤退: SBL 餘額日減 ≥10% (all / up_only 兩組)
  借券雷達: 議借量 > 5d 均 × 2 且 利率 <1% (low_rate) 或 >7% (high_rate)
訊號於盤後資料產生 → 進場 = 隔日還原開盤。統計/成本/基準同 backtest_lib。

偏差說明（相較 brief 參考碼，controller 授權的硬化）：
  D1. 不快取空回應：fetch_lending 拿到空 data 時直接 return {}，不寫 cache 檔，
      避免 HTTP 402 quota ban 把空結果污染快取 7 天。
  D2. 速率限制 + 停火偵測：每次未命中快取的 _fm 呼叫後 sleep(0.03)；
      追蹤連續空回應數，≥100 連續全空 → 印 ABORT 訊息並 sys.exit(3)。
      重置條件：任何一次 fetch 有資料回來就重置計數。
  D3. 建議用 nohup 背景執行（首跑約 30-60 分鐘），快取使重跑可恢復。

欄位核實（2026-07-06 field probe）：
  TaiwanStockSecuritiesLending row: {date(YYYY-MM-DD), stock_id, transaction_type('議借'/'競價'),
  volume(整數,張), fee_rate(float,%), close, original_return_date, original_lending_period}
  → fetch_lending 直接用 volume/fee_rate，date strip '-'；議借 = transaction_type=='議借'。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                     # noqa: E402
from backtest_prices import load_panel, _fm, _token, BT_CACHE  # noqa: E402
from tw_turnaround_backtest import fetch_sbl                   # noqa: E402


def fetch_lending(code: str, token: str) -> dict:
    """議借 (negotiated) 日彙總: {date(YYYYMMDD): {vol(張), rate(量加權%)}}。快取 7 天。

    D1 偏差：data 為空時直接 return {}，不寫 cache 檔——避免 HTTP 402 quota ban
    把空結果快取 7 天，等同永久跳過該股。
    """
    p = os.path.join(BT_CACHE, f"lend_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        return json.load(open(p))
    data = _fm("TaiwanStockSecuritiesLending", code, "2024-12-01", token)
    time.sleep(0.03)  # D2: 速率限制
    if not data:
        return {}  # D1: 不快取空回應
    agg = {}
    for r in data:
        # 只取議借（與 live 借券雷達同口徑）
        if r.get("transaction_type") != "議借":
            continue
        d = (r.get("date") or "").replace("-", "")
        v = float(r.get("volume") or 0)
        rate = float(r.get("fee_rate") or 0)
        if not d or v <= 0:
            continue
        a = agg.setdefault(d, {"vol": 0.0, "rv": 0.0})
        a["vol"] += v
        a["rv"] += v * rate
    out = {d: {"vol": a["vol"], "rate": a["rv"] / a["vol"]}
           for d, a in agg.items() if a["vol"] > 0}
    if not out:
        return {}  # D1: 有 raw data 但無議借記錄，不快取
    json.dump(out, open(p, "w"))
    return out


def _study(events, panel, horizons, cost, label):
    """events = [(code, dateYYYYMMDD)] → {h: summary}。"""
    out = {}
    for h in horizons:
        absr, excr, edges = [], [], []
        for code, date in events:
            r = panel.fwd(code, date, h, "next_open")
            if r is None:
                continue
            sr, tr = r
            absr.append(sr)
            excr.append(sr - tr)
            b = panel.matched_baseline(date, h)
            if b is not None:
                edges.append(sr - tr - b)
        s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
        out[str(h)] = s
        if s.get("n"):
            print(f"  [{label} H={h}] n={s['n']} 超額 {s['exc_mean']:+.2f}% "
                  f"CI {s['exc_ci']} 淨 {s['net']:+.2f}% edge {s.get('edge_mean')}")
    return out


def run(horizons, cost, min_balance_zhang=200, smoke=False):
    token = _token()
    panel = load_panel()
    max_h = max(horizons)
    ev_sbl_all, ev_sbl_up = [], []
    ev_low_raw, ev_high_raw = [], []
    codes = sorted(panel.stocks)
    if smoke:
        codes = codes[:50]
        print(f"[smoke] 只跑前 50 檔: {codes[:5]}...")

    consecutive_empty = 0  # D2: 連續空回應計數

    for n, code in enumerate(codes):
        if (n + 1) % 200 == 0:
            print(f"  {n+1}/{len(codes)} ev_sbl={len(ev_sbl_all)} ev_low={len(ev_low_raw)}",
                  file=sys.stderr)

        # ── 空頭撤退：SBL 日減 ≥10%（前日餘額 ≥ min_balance 張，避免小基數雜訊）
        sbl = fetch_sbl(code, token)
        rows, didx = panel._by_code[code]
        fires_all, fires_up = [], []
        for j in range(1, len(sbl)):
            prev, cur_bal = sbl[j - 1]["balance"], sbl[j]["balance"]
            d = sbl[j]["date"]
            if prev < min_balance_zhang or d not in didx:
                continue
            if (cur_bal - prev) / prev <= -0.10:
                i = didx[d]
                fires_all.append(i)
                # up_only：當日收漲（close > prev close）
                if i > 0 and rows[i]["close"] > rows[i - 1]["close"]:
                    fires_up.append(i)
        for i in bl.dedup_cooldown(sorted(set(fires_all)), max_h):
            ev_sbl_all.append((code, rows[i]["date"]))
        for i in bl.dedup_cooldown(sorted(set(fires_up)), max_h):
            ev_sbl_up.append((code, rows[i]["date"]))

        # ── 借券雷達：議借量 >5d 均 × 2 + 利率帶
        lend = fetch_lending(code, token)

        # D2: 空回應計數（連續 100 全空才 abort）
        if lend:
            consecutive_empty = 0
        else:
            consecutive_empty += 1
            if consecutive_empty >= 100:
                print(
                    "\n[ABORT] 連續 100 檔 lending 空回應 — 疑似 FinMind quota ban，"
                    "稍後重跑 (已抓部分已快取)",
                    file=sys.stderr
                )
                sys.exit(3)

        ldates = sorted(lend)
        for j in range(5, len(ldates)):
            d = ldates[j]
            if d not in didx:
                continue
            prev5 = [lend[ldates[k]]["vol"] for k in range(j - 5, j)]
            avg5 = sum(prev5) / 5
            cur = lend[d]
            if avg5 <= 0 or cur["vol"] <= avg5 * 2:
                continue
            i = didx[d]
            if cur["rate"] < 1.0:
                ev_low_raw.append((code, rows[i]["date"], i))
            elif cur["rate"] > 7.0:
                ev_high_raw.append((code, rows[i]["date"], i))

    # 議借事件 cooldown（per code）
    def _dedup(evs):
        by = {}
        for code, date, i in evs:
            by.setdefault(code, []).append(i)
        out = []
        for code, fires in by.items():
            rows_c, _ = panel._by_code[code]
            for i in bl.dedup_cooldown(sorted(set(fires)), max_h):
                out.append((code, rows_c[i]["date"]))
        return out

    ev_low = _dedup(ev_low_raw)
    ev_high = _dedup(ev_high_raw)

    print(f"\n空頭撤退 all={len(ev_sbl_all)} up_only={len(ev_sbl_up)}  "
          f"議借 low={len(ev_low)} high={len(ev_high)}")

    return {
        "sbl_retreat": {
            "all": _study(ev_sbl_all, panel, horizons, cost, "撤退all"),
            "up_only": _study(ev_sbl_up, panel, horizons, cost, "撤退up"),
        },
        "lending_surge": {
            "low_rate": _study(ev_low, panel, horizons, cost, "議借<1%"),
            "high_rate": _study(ev_high, panel, horizons, cost, "議借>7%"),
        },
        "params": {
            "min_balance_zhang": min_balance_zhang,
            "cost": cost,
            "horizons": horizons,
        },
        "event_counts": {
            "sbl_all": len(ev_sbl_all),
            "sbl_up_only": len(ev_sbl_up),
            "lending_low": len(ev_low),
            "lending_high": len(ev_high),
        },
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--min-balance", type=int, default=200)
    ap.add_argument("--json-out")
    ap.add_argument("--smoke", action="store_true", help="只跑前 50 檔做煙霧測試")
    args = ap.parse_args()
    r = run(args.horizon, args.cost, args.min_balance, smoke=args.smoke)
    if args.json_out:
        json.dump(
            {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "result": r},
            open(args.json_out, "w", encoding="utf-8"),
            ensure_ascii=False,
        )
        print(f"[json] 寫入 {args.json_out}", file=sys.stderr)

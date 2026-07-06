#!/usr/bin/env python3
"""訊號成效週報 CLI — 5 策略推播歷史 → T+h 實際報酬 → cache/signal_outcomes.json + TG 推播。

用法：
  python3 concept_momentum/run_outcomes.py              # 算完存檔，不推 TG
  python3 concept_momentum/run_outcomes.py --telegram   # 推摘要到 TG

配額保護（FinMind sponsor 每日限額）：
  - 每次 API 呼叫前 sleep 0.03s
  - 空回應不寫 cache（避免垃圾覆蓋）
  - 個股失敗 → skip + 計入 n_px_failed
  - >50% 個股失敗 → [ABORT] 列印後 sys.exit(3)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CACHE_DIR = os.path.join(HERE, "cache")
PX_CACHE_DIR = os.path.join(CACHE_DIR, "outcomes_px")
OUTCOMES_JSON = os.path.join(CACHE_DIR, "signal_outcomes.json")
START_DATE = "2026-04-01"
DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

sys.path.insert(0, HERE)
import signal_outcomes as so

os.makedirs(PX_CACHE_DIR, exist_ok=True)


# ─── FinMind helpers ───────────────────────────────────────────────────────────

def _finmind_call(dataset: str, params: dict, token: str) -> list[dict]:
    """Raw FinMind call with rate-limit retry. Raises on non-200 / HTTP error."""
    import urllib.error
    base = "https://api.finmindtrade.com/api/v4/data"
    full = {"dataset": dataset, "token": token, **params}
    url = f"{base}?{urllib.parse.urlencode(full)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code == 402:
                raise RuntimeError(f"FinMind HTTP 402 (quota)")
            if e.code == 429 and attempt == 0:
                time.sleep(60)
                continue
            body = e.read().decode() if hasattr(e, "read") else str(e)
            raise RuntimeError(f"FinMind {dataset} HTTP {e.code}: {body[:200]}")
    if payload.get("status") != 200:
        msg = payload.get("msg", "")
        raise RuntimeError(f"FinMind {dataset} error: {msg}")
    return payload.get("data", [])


def _is_stale(path: str, ttl_hours: float = 23.0) -> bool:
    """True if file doesn't exist or is older than ttl_hours."""
    if not os.path.exists(path):
        return True
    age = time.time() - os.path.getmtime(path)
    return age > ttl_hours * 3600


def _load_taiex(token: str) -> tuple[dict, list[str]]:
    """Fetch TAIEX price since START_DATE. Returns (date→{open,close}, sorted trading_dates)."""
    cache_path = os.path.join(PX_CACHE_DIR, "TAIEX.json")
    if not _is_stale(cache_path):
        data = json.load(open(cache_path, encoding="utf-8"))
        taiex = data["taiex"]
        trading_dates = data["trading_dates"]
        print(f"  [cache] TAIEX {len(trading_dates)} days")
        return taiex, trading_dates

    print(f"  [fetch] TAIEX from {START_DATE}…", flush=True)
    time.sleep(0.03)
    rows = _finmind_call("TaiwanStockPrice", {
        "data_id": "TAIEX",
        "start_date": START_DATE,
        "end_date": datetime.today().strftime("%Y-%m-%d"),
    }, token)
    if not rows:
        raise RuntimeError("TAIEX returned empty — not caching")
    taiex = {}
    for r in rows:
        d = r["date"].replace("-", "")
        taiex[d] = {"open": float(r.get("open") or 0),
                    "close": float(r.get("close") or 0)}
    trading_dates = sorted(taiex.keys())
    payload = {"taiex": taiex, "trading_dates": trading_dates,
               "generated": datetime.now().isoformat()}
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"  [cache] TAIEX {len(trading_dates)} days saved")
    return taiex, trading_dates


def _load_stock_px(code: str, token: str) -> dict:
    """Fetch TaiwanStockPriceAdj for one stock. Returns {date: {aopen,aclose}}.
    Returns {} on error (caller skips & counts)."""
    cache_path = os.path.join(PX_CACHE_DIR, f"{code}.json")
    if not _is_stale(cache_path):
        try:
            raw = json.load(open(cache_path, encoding="utf-8"))
            return raw.get("px", {})
        except Exception:
            pass  # corrupt cache → re-fetch

    time.sleep(0.03)
    try:
        rows = _finmind_call("TaiwanStockPriceAdj", {
            "data_id": code,
            "start_date": START_DATE,
            "end_date": datetime.today().strftime("%Y-%m-%d"),
        }, token)
    except RuntimeError as e:
        print(f"  [WARN] {code}: {e}", flush=True)
        return {}

    if not rows:
        print(f"  [WARN] {code}: empty response (not caching)", flush=True)
        return {}

    px = {}
    for r in rows:
        d = r["date"].replace("-", "")
        px[d] = {"aopen": float(r.get("open") or 0),
                 "aclose": float(r.get("close") or 0)}
    payload = {"px": px, "generated": datetime.now().isoformat()}
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return px


# ─── Extra aggregations ────────────────────────────────────────────────────────

def _abcd_bucket_summary(signals_with_ret: list[dict], horizons=(1, 5, 10, 20)) -> dict:
    """TR abcd_score 分桶：>=3 vs <3，以及 per-score (0/1/2/3/4)。"""
    buckets: dict[str, dict] = {}
    for r in signals_with_ret:
        if r["strategy"] != "turnaround_relay":
            continue
        score = r["meta"].get("abcd_score")
        if score is None:
            continue
        labels = [f"score_{score}", "gte3" if score >= 3 else "lt3"]
        for lbl in labels:
            b = buckets.setdefault(lbl, {str(h): {"abs": [], "exc": []} for h in horizons})
            for h, v in r["ret"].items():
                if h in b:
                    b[h]["abs"].append(v["abs"])
                    b[h]["exc"].append(v["exc"])
    result = {}
    for lbl, hs in buckets.items():
        result[lbl] = {}
        for h, v in hs.items():
            n = len(v["exc"])
            if not n:
                continue
            result[lbl][h] = {
                "n": n,
                "exc_mean": round(sum(v["exc"]) / n, 2),
                "exc_med": round(sorted(v["exc"])[n // 2], 2),
                "win": round(sum(1 for x in v["abs"] if x > 0) / n * 100, 0),
                "beat": round(sum(1 for x in v["exc"] if x > 0) / n * 100, 0),
            }
    return result


def _sw_score_tercile_summary(signals_with_ret: list[dict], horizons=(1, 5, 10, 20)) -> dict:
    """SW second_wave_score 三分位分桶。"""
    sw_recs = [r for r in signals_with_ret if r["strategy"] == "second_wave"
               and r["meta"].get("second_wave_score") is not None]
    if not sw_recs:
        return {}
    scores = sorted(r["meta"]["second_wave_score"] for r in sw_recs)
    n = len(scores)
    q1 = scores[n // 3]
    q2 = scores[(n * 2) // 3]

    def _label(s):
        if s <= q1:
            return "low_tercile"
        if s <= q2:
            return "mid_tercile"
        return "high_tercile"

    buckets: dict[str, dict] = {}
    for r in sw_recs:
        lbl = _label(r["meta"]["second_wave_score"])
        b = buckets.setdefault(lbl, {str(h): {"abs": [], "exc": []} for h in horizons})
        for h, v in r["ret"].items():
            if h in b:
                b[h]["abs"].append(v["abs"])
                b[h]["exc"].append(v["exc"])

    result = {}
    for lbl, hs in buckets.items():
        result[lbl] = {}
        for h, v in hs.items():
            n = len(v["exc"])
            if not n:
                continue
            result[lbl][h] = {
                "n": n,
                "exc_mean": round(sum(v["exc"]) / n, 2),
                "exc_med": round(sorted(v["exc"])[n // 2], 2),
                "win": round(sum(1 for x in v["abs"] if x > 0) / n * 100, 0),
                "beat": round(sum(1 for x in v["exc"] if x > 0) / n * 100, 0),
            }
    return result


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API_URL.format(token=bot_token)
    max_len = 4000
    chunks = []
    if len(message) <= max_len:
        chunks = [message]
    else:
        cur = ""
        for line in message.split("\n"):
            if len(cur) + len(line) + 1 > max_len:
                chunks.append(cur)
                cur = line
            else:
                cur = cur + "\n" + line if cur else line
        if cur:
            chunks.append(cur)
    all_ok = True
    for c in chunks:
        try:
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": c}).encode()
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp_body = r.read().decode()
            resp_json = json.loads(resp_body)
            print(f"  [TG] ok:{resp_json.get('ok')} msg_id:{resp_json.get('result',{}).get('message_id','?')}")
        except Exception as e:
            print(f"[ERROR] Telegram: {e}", file=sys.stderr)
            all_ok = False
    return all_ok


def _build_tg_report(outcomes: dict) -> str:
    summary = outcomes.get("summary", {})
    abcd = outcomes.get("abcd_buckets", {})
    now_str = outcomes.get("generated", "")[:16]
    lines = [f"📈 訊號成效週報 ({now_str})", ""]

    strat_display = {
        "turnaround_relay": "🔄 轉機接力",
        "second_wave":      "🌊 強勢第二波",
        "broker_radar":     "🎯 主力雷達",
        "lending_radar":    "🌙 借券雷達",
        "short_retreat":    "🏳 空頭撤退",
    }
    for strat, label in strat_display.items():
        s = summary.get(strat, {})
        if not s:
            lines.append(f"{label}: 無數據")
            continue
        h1 = s.get("1", {})
        h5 = s.get("5", {})
        h20 = s.get("20", {})
        n = h5.get("n") or h1.get("n") or 0
        lines.append(f"{label} (n={n})")
        for hk, hd, lbl in [("1", h1, "T+1"), ("5", h5, "T+5"), ("20", h20, "T+20")]:
            if not hd:
                continue
            lines.append(f"  {lbl}: 超額均{hd['exc_mean']:+.1f}% 勝率{hd['win']:.0f}%")

    # TR abcd 分桶
    gte3 = abcd.get("gte3", {})
    lt3 = abcd.get("lt3", {})
    if gte3 or lt3:
        lines.append("")
        lines.append("🔬 TR abcd 分桶 (T+5 超額均)")
        for lbl_str, bd in [("abcd≥3", gte3), ("abcd<3", lt3)]:
            h5b = bd.get("5", {})
            if h5b:
                lines.append(f"  {lbl_str}: n={h5b['n']} 超額{h5b['exc_mean']:+.1f}% 勝率{h5b['win']:.0f}%")

    # quota info
    n_failed = outcomes.get("n_px_failed", 0)
    n_total = outcomes.get("n_px_codes", 0)
    if n_failed:
        lines.append(f"\n⚠ {n_failed}/{n_total} 個股 px 抓取失敗 (quota?)")
    return "\n".join(lines)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--bot-token", default=os.environ.get("TG_BOT_TOKEN", ""))
    p.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    p.add_argument("--token", default=os.environ.get("FINMIND_TOKEN", ""))
    args = p.parse_args()

    if not args.token:
        print("[ERROR] FINMIND_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    print("=== run_outcomes ===", flush=True)

    # 1. TAIEX + trading calendar
    taiex, trading_dates = _load_taiex(args.token)
    print(f"  trading_dates: {len(trading_dates)} days, "
          f"{trading_dates[0]}..{trading_dates[-1]}")

    # 2. Load signals
    signals = so.load_signals(CACHE_DIR, trading_dates)
    print(f"  signals loaded: {len(signals)}")
    for strat in so.STRATS:
        n = sum(1 for s in signals if s["strategy"] == strat)
        print(f"    {strat}: {n}")

    # 3. Fetch prices for all unique codes
    codes = sorted({s["code"] for s in signals})
    print(f"  unique codes: {len(codes)}", flush=True)

    px_cache: dict[str, dict] = {}
    n_failed = 0
    for i, code in enumerate(codes):
        if i % 20 == 0:
            print(f"  px fetch {i}/{len(codes)}…", flush=True)
        px = _load_stock_px(code, args.token)
        px_cache[code] = px
        if not px:
            n_failed += 1

    fail_rate = n_failed / len(codes) if codes else 0
    print(f"  px: {len(codes)} codes, {n_failed} failed ({fail_rate*100:.0f}%)")
    if fail_rate > 0.5:
        print(f"[ABORT] quota suspicion: {n_failed}/{len(codes)} codes failed",
              file=sys.stderr)
        sys.exit(3)

    # 4. Compute outcomes
    def px_fetch(code):
        return px_cache.get(code, {})

    outcomes = so.compute_outcomes(signals, px_fetch, taiex,
                                   trading_dates, horizons=(1, 5, 10, 20))

    # 5. Extra aggregations
    outcomes["abcd_buckets"] = _abcd_bucket_summary(outcomes["signals"])
    outcomes["sw_score_terciles"] = _sw_score_tercile_summary(outcomes["signals"])
    outcomes["n_px_failed"] = n_failed
    outcomes["n_px_codes"] = len(codes)
    outcomes["generated"] = datetime.now().isoformat()

    # Print per-strategy summary
    print("\n--- Summary ---")
    for strat, sh in outcomes["summary"].items():
        for hk, hd in sorted(sh.items(), key=lambda x: int(x[0])):
            print(f"  {strat} T+{hk}: n={hd['n']} "
                  f"exc_mean={hd['exc_mean']:+.2f}% exc_med={hd['exc_med']:+.2f}% "
                  f"win={hd['win']:.0f}% beat={hd['beat']:.0f}%")

    # Save
    # Strip signal list for JSON size sanity (keep last 500)
    # Sort by entry_date then strategy so tail contains mixed strategies (not strategy-major)
    save_obj = {k: v for k, v in outcomes.items() if k != "signals"}
    # Secondary sort by code (not strategy) so same-date entries are interleaved across strategies
    all_signals = sorted(outcomes["signals"], key=lambda r: (r.get("entry_date", ""), r.get("code", "")))
    save_obj["signals"] = all_signals[-500:]
    with open(OUTCOMES_JSON, "w", encoding="utf-8") as f:
        json.dump(save_obj, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved → {OUTCOMES_JSON}")

    # 6. Optional TG push
    if args.telegram:
        if not args.bot_token:
            print("[ERROR] TG_BOT_TOKEN not set", file=sys.stderr)
            sys.exit(1)
        msg = _build_tg_report(outcomes)
        print("\n--- TG message ---")
        print(msg)
        ok = send_telegram(msg, args.bot_token, args.chat_id)
        print(f"  TG send: {'ok' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()

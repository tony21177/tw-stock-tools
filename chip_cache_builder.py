#!/usr/bin/env python3
"""每日分點 BSR 快取建置器 — 動態清單持續累積籌碼歷史.

broker_monitor（18:00）只抓「融資餘額 Top 200」，漏掉低融資的族群成分股 /
強勢股 / 熱門股。本器在其後（19:30）跑，抓一份**動態 union**：
  - 族群成分股（concepts.json themes 全成員）
  - 強勢股候選（近 N 日 second_wave_history）
  - 推播 watchlist（chip_narrative_watchlist.json）
  - 熱門股（當日成交金額 Top hot_n）
**跳過當日已快取的**（broker_monitor 已抓的不重抓）→ 只補缺口，
每檔 analyze() 會寫 bsr_cache + chip_price_history，資料逐日累積。

用法:
  chip_cache_builder.py                 # 抓缺口
  chip_cache_builder.py --list-only     # 只印 union 不抓
  chip_cache_builder.py --hot-n 60      # 熱門股取前 60（0=不加）
  chip_cache_builder.py --max 250       # union 上限（防爆時間）

cron（19:30 平日，is_trading_day 守門，broker_monitor 18:00 之後）:
  30 19 * * 1-5 ... is_trading_day.py && FINMIND_TOKEN=... \
    python3 chip_cache_builder.py >> chip_cache_builder.log 2>&1
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CM = os.path.join(HERE, "concept_momentum")
CONCEPTS = os.path.join(CM, "cache", "concepts.json")
SECOND_WAVE_DIR = os.path.join(CM, "cache", "second_wave_history")
WATCHLIST = os.path.join(CM, "chip_narrative_watchlist.json")
BSR_CACHE = os.path.join(HERE, "bsr_cache")


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _concept_codes() -> set[str]:
    try:
        t = json.load(open(CONCEPTS))
        out: set[str] = set()
        for th in t.get("themes", {}).values():
            out.update(str(c) for c in th.get("stocks", []))
        return out
    except Exception as e:
        _log(f"[WARN] concepts 讀取失敗: {e}")
        return set()


def _second_wave_codes(days: int = 5) -> set[str]:
    out: set[str] = set()
    for f in sorted(glob.glob(os.path.join(SECOND_WAVE_DIR, "*.json")))[-days:]:
        try:
            for c in json.load(open(f)).get("candidates", []):
                if c.get("code"):
                    out.add(str(c["code"]))
        except Exception:
            continue
    return out


def _watchlist_codes() -> set[str]:
    try:
        return set(json.load(open(WATCHLIST)).get("codes", []))
    except Exception:
        return set()


def _hot_codes(token: str, hot_n: int) -> set[str]:
    """當日成交金額 Top hot_n（僅 4 位數普通股）。無 token/失敗回空。"""
    if hot_n <= 0 or not token:
        return set()
    import re
    sys.path.insert(0, HERE)
    try:
        import finmind_client as fc
        today = datetime.now().strftime("%Y-%m-%d")
        rows = fc._call("TaiwanStockPrice",
                        {"start_date": today, "end_date": today}, token)
        rows = [r for r in rows
                if re.fullmatch(r"\d{4}", str(r.get("stock_id", "")))
                and not str(r.get("stock_id", "")).startswith("00")  # 排除 ETF
                and (r.get("Trading_money") or 0) > 0]
        rows.sort(key=lambda r: -(r.get("Trading_money") or 0))
        return {str(r["stock_id"]) for r in rows[:hot_n]}
    except Exception as e:
        _log(f"[WARN] 熱門股讀取失敗: {e}")
        return set()


def build_universe(token: str = "", hot_n: int = 60) -> dict:
    """回 {codes: sorted list, sources: {code: [tags]}}。"""
    concept = _concept_codes()
    sw = _second_wave_codes()
    watch = _watchlist_codes()
    hot = _hot_codes(token, hot_n)
    sources: dict[str, list[str]] = {}
    for tag, s in (("族群", concept), ("強勢", sw),
                   ("watch", watch), ("熱門", hot)):
        for c in s:
            sources.setdefault(c, []).append(tag)
    return {"codes": sorted(sources), "sources": sources,
            "counts": {"族群": len(concept), "強勢": len(sw),
                       "watch": len(watch), "熱門": len(hot)}}


def _cached_today(code: str, yyyymmdd: str) -> bool:
    return os.path.exists(os.path.join(
        BSR_CACHE, f"{code}_{yyyymmdd}_prices.json"))


def _wait_for_broker_monitor(max_wait_sec: int = 2400) -> None:
    """broker_monitor 執行中就等它結束（TPEx Xvfb :99 不能並行）。"""
    import subprocess
    waited = 0
    while waited < max_wait_sec:
        try:
            r = subprocess.run(["pgrep", "-f", "tw_broker_monitor.py"],
                               capture_output=True, text=True, timeout=5)
        except Exception:
            return
        if r.returncode != 0:      # 沒在跑
            if waited:
                _log(f"broker_monitor 已結束，等了 {waited}s，開工")
            return
        if waited == 0:
            _log("broker_monitor 執行中，等它結束再抓（避免 Xvfb 搶用）…")
        time.sleep(30)
        waited += 30
    _log(f"等 broker_monitor 逾 {max_wait_sec}s，仍在跑 — 仍開工（風險自負）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--hot-n", type=int, default=60)
    ap.add_argument("--max", type=int, default=260,
                    help="union 上限（防爆時間，超過截斷）")
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    token = os.environ.get("FINMIND_TOKEN", "")
    uni = build_universe(token, hot_n=args.hot_n)
    codes = uni["codes"]
    _log(f"union {len(codes)} 檔（族群{uni['counts']['族群']} 強勢"
         f"{uni['counts']['強勢']} watch{uni['counts']['watch']} "
         f"熱門{uni['counts']['熱門']}）")
    if len(codes) > args.max:
        _log(f"超過上限 {args.max}，截斷（保留族群/強勢/watch 優先）")
        # 優先保留非「純熱門」的（族群/強勢/watch）
        pri = [c for c in codes if uni["sources"][c] != ["熱門"]]
        extra = [c for c in codes if uni["sources"][c] == ["熱門"]]
        codes = (pri + extra)[:args.max]

    if args.list_only:
        for c in codes:
            print(c, "+".join(uni["sources"][c]))
        return

    today = datetime.now().strftime("%Y%m%d")
    already = [c for c in codes if _cached_today(c, today)]
    todo = [c for c in codes if c not in set(already)]
    _log(f"當日已快取 {len(already)}，待補 {len(todo)}")

    # broker_monitor（18:00 長工，最長 ~105 分）用同一個 Xvfb :99 跑 TPEx
    # Playwright — 同時跑會搶 display。若還在跑，等它結束（最多 40 分）再開工。
    _wait_for_broker_monitor(max_wait_sec=2400)

    import tw_chip_price
    ok, fail = 0, []
    for i, code in enumerate(todo):
        try:
            r = tw_chip_price.analyze(code)  # 寫 bsr_cache + chip_price_history
            if r and _cached_today(code, r.get("date", today)):
                ok += 1
            else:
                fail.append(code)
        except Exception as e:
            print(f"[WARN] {code}: {e}", file=sys.stderr)
            fail.append(code)
        time.sleep(args.delay)
        if (i + 1) % 25 == 0:
            _log(f"進度 {i+1}/{len(todo)} 成功 {ok}")
    _log(f"完成：新增 {ok}/{len(todo)}（失敗 {len(fail)}）"
         f"{'；失敗前10: '+','.join(fail[:10]) if fail else ''}")
    _log(f"當日分點覆蓋合計 ~{len(already)+ok} 檔")


if __name__ == "__main__":
    main()

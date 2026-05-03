#!/usr/bin/env python3
"""
沉睡巨人篩選器 (tw_dormant_giants)

找出符合以下條件的「曾經輝煌，沉寂多年，正在打底」的標的：

  A 曾經 10 倍股: 還原收盤峰值 / 峰值前低點 ≥ 10x
                  (避免捕捉到 Yahoo 資料起點即巔峰，要求峰前至少 3 年資料)
  B 從峰值修正 ≥ 50%: 現在收盤 ≤ 50% × 峰值
  C 峰值距今 ≥ 5 年: 已經夠久沒被炒
  D 近 5 年無顯著炒作:
      - 近 5 年最高 / 最低 < 3x
      - 任何 60 td 滑動視窗內，max/min < 1.5x (沒有突發飆漲)
  E 近期長時間量縮震盪整理:
      - 近 60 td 收盤最高 / 最低 - 1 < 15% (狹窄震盪)
      - 近 60 td 平均量 / 3 年平均量 ≤ 30% (量縮)

設計動機: 找「籌碼徹底洗淨、無人聞問」的潛在 turnaround 標的。這類股票若有
新催化事件 (產業景氣回暖、新題材、業務轉型)，因為沒有套牢盤、波動率被壓到底，
向上爆發力大且阻力小。

資料源:
  Yahoo Finance: 18 年還原收盤 (.TW 上市 / .TWO 上櫃)，已處理 split + dividend，
                 多數 case 也涵蓋減資。FinMind TaiwanStockPriceAdj 需付費，本工具用 Yahoo 替代。
  Universe: FinMind TaiwanStockInfo (與 tw_turnaround_screener 共享 universe_all 快取)
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
try:
    from stock_names import get_name as _get_zh_name
except Exception:
    def _get_zh_name(code, fallback=""):
        return fallback or code

CACHE_DIR = os.path.join(HERE, "dormant_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


# ============================================================
# HTTP helpers
# ============================================================

def http_json(url: str, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(5)
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return None
    return None


# ============================================================
# Universe loader (reuse pattern from tw_turnaround_screener)
# ============================================================

def load_universe(arg: str) -> list[tuple[str, str]]:
    """Returns list of (code, name)."""
    if "," in arg or arg.isdigit():
        codes = [c.strip() for c in arg.split(",") if c.strip()]
        return [(c, _get_zh_name(c, c)) for c in codes]

    if arg == "all":
        cache_path = os.path.join(HERE, "screener_cache", "universe_all.json")
        if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < 7 * 86400:
            with open(cache_path) as f:
                return [tuple(x) for x in json.load(f)]
        # Fallback: fetch from FinMind
        token = os.environ.get("FINMIND_TOKEN", "")
        url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        if token:
            url += f"&token={token}"
        data = http_json(url)
        if not data or "data" not in data:
            print("[ERROR] 無法取得 TaiwanStockInfo", file=sys.stderr)
            sys.exit(1)
        seen = set()
        out = []
        for r in data["data"]:
            code = str(r.get("stock_id", "")).strip()
            name = str(r.get("stock_name", "")).strip()
            mtype = r.get("type", "")
            if not re.fullmatch(r"\d{4}", code):
                continue
            if mtype not in ("twse", "tpex"):
                continue
            if code in seen:
                continue
            seen.add(code)
            out.append((code, name))
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(out, f, ensure_ascii=False)
        return out

    # concepts mode
    if arg == "concepts":
        cpath = os.path.join(HERE, "concept_momentum", "cache", "concepts.json")
        with open(cpath) as f:
            data = json.load(f)
        out = []
        seen = set()
        for theme in data.get("themes", {}).values():
            for code in theme.get("stocks", []):
                if code in seen:
                    continue
                seen.add(code)
                out.append((code, _get_zh_name(code, code)))
        return out

    # treat as comma list
    return [(c.strip(), _get_zh_name(c.strip(), c.strip())) for c in arg.split(",") if c.strip()]


# ============================================================
# Yahoo adjusted-close fetcher (cache 7 days)
# ============================================================

def fetch_yahoo_long(code: str, years: int = 18) -> dict:
    """Fetch ~years of daily OHLCV from Yahoo (.TW or .TWO).
    Returns {market: '上市'/'上櫃', rows: [{ts, adj, close, volume}, ...]} or {}.
    Cache for 7 days."""
    cache_path = os.path.join(CACHE_DIR, f"yh_{code}.json")
    if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < 7 * 86400:
        with open(cache_path) as f:
            return json.load(f)

    end = int(time.time())
    start = end - years * 366 * 86400
    for sfx, market in (".TW", "上市"), (".TWO", "上櫃"):
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{sfx}"
               f"?period1={start}&period2={end}&interval=1d&events=history")
        d = http_json(url)
        if not d or not d.get("chart", {}).get("result"):
            continue
        res = d["chart"]["result"][0]
        if not res.get("timestamp"):
            continue
        ts = res["timestamp"]
        adj_arr = res["indicators"]["adjclose"][0]["adjclose"]
        q = res["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            if adj_arr[i] is None or q["close"][i] is None:
                continue
            rows.append({
                "ts": int(t),
                "adj": float(adj_arr[i]),
                "close": float(q["close"][i]),
                "volume": int(q["volume"][i] or 0),
            })
        if not rows:
            continue
        out = {"market": market, "rows": rows}
        with open(cache_path, "w") as f:
            json.dump(out, f)
        return out

    # Cache empty result so we don't keep hitting Yahoo
    with open(cache_path, "w") as f:
        json.dump({}, f)
    return {}


# ============================================================
# Filter pipeline
# ============================================================

def filter_a_ever_10x(rows: list[dict], min_multiple: float = 10.0,
                     min_pre_peak_years: int = 3) -> tuple[bool, dict]:
    """Filter A: peak adj / min adj before peak ≥ min_multiple.
    Require at least min_pre_peak_years of data before peak so we can trust the base."""
    if len(rows) < 250 * min_pre_peak_years:
        return False, {"reason": "資料不足"}
    peak_idx = max(range(len(rows)), key=lambda i: rows[i]["adj"])
    peak = rows[peak_idx]
    # Pre-peak window: at least min_pre_peak_years before peak
    cutoff_ts = peak["ts"] - min_pre_peak_years * 365 * 86400
    pre_peak = [r for r in rows[:peak_idx] if r["ts"] <= cutoff_ts]
    if not pre_peak:
        return False, {"reason": f"峰前 < {min_pre_peak_years} 年資料"}
    base_idx = min(range(len(pre_peak)), key=lambda i: pre_peak[i]["adj"])
    base = pre_peak[base_idx]
    multiple = peak["adj"] / max(base["adj"], 0.01)
    metrics = {
        "peak_adj": peak["adj"],
        "peak_date": datetime.fromtimestamp(peak["ts"]).strftime("%Y-%m-%d"),
        "base_adj": base["adj"],
        "base_date": datetime.fromtimestamp(base["ts"]).strftime("%Y-%m-%d"),
        "multiple": multiple,
        "peak_ts": peak["ts"],
    }
    return multiple >= min_multiple, metrics


def filter_b_drawdown(rows: list[dict], peak_adj: float,
                     max_current_pct: float = 0.5) -> tuple[bool, dict]:
    """Filter B: current adj ≤ max_current_pct × peak."""
    cur = rows[-1]
    pct = cur["adj"] / peak_adj
    metrics = {"current_adj": cur["adj"], "current_pct": pct}
    return pct <= max_current_pct, metrics


def filter_c_age(peak_ts: int, min_years: int = 5) -> tuple[bool, dict]:
    now = time.time()
    yrs = (now - peak_ts) / 365.25 / 86400
    return yrs >= min_years, {"years_since_peak": yrs}


def filter_d_no_recent_rally(rows: list[dict], max_5y_ratio: float = 3.0,
                             max_6m_ratio: float = 1.5) -> tuple[bool, dict]:
    """Filter D: last 5 years no major rally.
    - max(adj) / min(adj) over 5y < max_5y_ratio
    - any rolling 120 td (~6 months), max/min < max_6m_ratio"""
    cutoff = time.time() - 5 * 365.25 * 86400
    recent = [r for r in rows if r["ts"] >= cutoff]
    if len(recent) < 250 * 4:  # need at least ~4 years of data
        return False, {"reason": "近 5 年資料不足"}
    mx5 = max(recent, key=lambda r: r["adj"])
    mn5 = min(recent, key=lambda r: r["adj"])
    ratio_5y = mx5["adj"] / max(mn5["adj"], 0.01)
    if ratio_5y >= max_5y_ratio:
        return False, {"reason": f"近 5 年最高/最低 {ratio_5y:.1f}x ≥ {max_5y_ratio}",
                       "ratio_5y": ratio_5y}

    # Rolling 120 td: find max ratio (max/min within window)
    window = 120
    max_window_ratio = 1.0
    max_window_date = ""
    for i in range(len(recent) - window):
        w = recent[i:i + window]
        adjs = [r["adj"] for r in w]
        ratio = max(adjs) / max(min(adjs), 0.01)
        if ratio > max_window_ratio:
            max_window_ratio = ratio
            max_window_date = datetime.fromtimestamp(w[-1]["ts"]).strftime("%Y-%m-%d")
    if max_window_ratio >= max_6m_ratio:
        return False, {"reason": f"近 5 年內 120td 滑窗最大 {max_window_ratio:.2f}x"
                                  f" @ {max_window_date}",
                       "ratio_5y": ratio_5y, "max_6m_ratio": max_window_ratio}

    return True, {"ratio_5y": ratio_5y, "max_6m_ratio": max_window_ratio}


def filter_e_dormancy(rows: list[dict], max_60d_range: float = 0.15,
                     vol_decline_ratio: float = 0.3) -> tuple[bool, dict]:
    """Filter E: recent 60 td narrow range + low volume."""
    if len(rows) < 60 * 13:  # need ~3 years
        return False, {"reason": "資料不足"}
    last60 = rows[-60:]
    adjs60 = [r["adj"] for r in last60]
    vol60 = [r["volume"] for r in last60]
    rng = max(adjs60) / max(min(adjs60), 0.01) - 1
    avg_vol_60 = sum(vol60) / 60
    # 3-year average volume (excluding last 60 days)
    long_window = rows[-60 * 13:-60]
    avg_vol_long = sum(r["volume"] for r in long_window) / max(len(long_window), 1)
    vol_ratio = avg_vol_60 / max(avg_vol_long, 1)
    metrics = {
        "range_60d": rng,
        "avg_vol_60d": avg_vol_60,
        "avg_vol_3y": avg_vol_long,
        "vol_ratio": vol_ratio,
    }
    if rng > max_60d_range:
        metrics["reason"] = f"60d 振幅 {rng*100:.1f}% > {max_60d_range*100:.0f}%"
        return False, metrics
    if vol_ratio > vol_decline_ratio:
        metrics["reason"] = f"60d 量 {vol_ratio:.2f}x 3y 均量 > {vol_decline_ratio}x"
        return False, metrics
    return True, metrics


# ============================================================
# Per-stock pipeline
# ============================================================

def process_one(code: str, name: str, args, counts: dict, lock) -> dict | None:
    yh = fetch_yahoo_long(code, years=18)
    if not yh or not yh.get("rows"):
        return None
    rows = yh["rows"]

    ok_a, m_a = filter_a_ever_10x(rows, args.min_peak, args.min_pre_peak_years)
    if not ok_a:
        return None
    with lock:
        counts["A"] += 1

    ok_b, m_b = filter_b_drawdown(rows, m_a["peak_adj"], args.max_current_pct)
    if not ok_b:
        return None
    with lock:
        counts["AB"] += 1

    ok_c, m_c = filter_c_age(m_a["peak_ts"], args.min_years_since_peak)
    if not ok_c:
        return None
    with lock:
        counts["ABC"] += 1

    ok_d, m_d = filter_d_no_recent_rally(rows, args.max_5y_ratio, args.max_6m_ratio)
    if not ok_d:
        return None
    with lock:
        counts["ABCD"] += 1

    ok_e, m_e = filter_e_dormancy(rows, args.max_60d_range, args.vol_decline_ratio)
    if not ok_e:
        return None
    with lock:
        counts["ABCDE"] += 1

    return {
        "code": code,
        "name": name,
        "market": yh.get("market", ""),
        "a": m_a,
        "b": m_b,
        "c": m_c,
        "d": m_d,
        "e": m_e,
    }


# ============================================================
# Output
# ============================================================

def format_report(survivors: list[dict], total: int, counts: dict) -> str:
    lines = []
    lines.append(f"💤 沉睡巨人篩選 — 曾 10 倍 / 跌 ≥50% / 沉睡 ≥5y / 量縮整理")
    lines.append(f"掃描 {total} 檔 → A:{counts['A']} → AB:{counts['AB']} "
                 f"→ ABC:{counts['ABC']} → ABCD:{counts['ABCD']} "
                 f"→ ABCDE: {counts['ABCDE']} 檔")
    lines.append("")

    if not survivors:
        lines.append("（無候選）")
        return "\n".join(lines)

    # Rank: by sleep duration × dormancy tightness
    def score(s):
        return (s["c"]["years_since_peak"] *
                (0.20 - s["e"]["range_60d"]) *
                (0.40 - s["e"]["vol_ratio"]) *
                s["a"]["multiple"] / 10)

    survivors.sort(key=score, reverse=True)

    lines.append(f"{'代號':<6}{'名稱':<10}{'峰值':<8}{'峰值年':<8}{'倍數':<7}"
                 f"{'今價':<8}{'剩餘%':<7}{'5y/6m':<10}{'60d振幅':<8}{'60d/3y量':<8}")
    lines.append("-" * 78)
    for s in survivors:
        a = s["a"]; b = s["b"]; c = s["c"]; d = s["d"]; e = s["e"]
        peak_year = a["peak_date"][:4]
        lines.append(
            f"{s['code']:<6}{s['name'][:8]:<10}"
            f"{a['peak_adj']:>5.0f}    "
            f"{peak_year:<8}"
            f"{a['multiple']:>4.1f}x  "
            f"{b['current_adj']:>5.1f}   "
            f"{b['current_pct']*100:>4.0f}%   "
            f"{d['ratio_5y']:.1f}/{d['max_6m_ratio']:.2f}  "
            f"{e['range_60d']*100:>4.1f}%   "
            f"{e['vol_ratio']:>4.2f}x"
        )

    # Detail blocks
    lines.append("")
    for s in survivors[:20]:
        a = s["a"]; b = s["b"]; c = s["c"]; d = s["d"]; e = s["e"]
        lines.append(f"\n{s['code']} {s['name']} [{s['market']}]")
        lines.append(f"  曾 10 倍：{a['base_date']} {a['base_adj']:.1f} → "
                     f"{a['peak_date']} {a['peak_adj']:.1f} = {a['multiple']:.1f}x")
        lines.append(f"  跌幅：今價 {b['current_adj']:.1f} = 峰值 {b['current_pct']*100:.0f}% "
                     f"(已跌 {(1-b['current_pct'])*100:.0f}%)")
        lines.append(f"  沉睡：峰值距今 {c['years_since_peak']:.1f} 年")
        lines.append(f"  近 5 年最高/最低 {d['ratio_5y']:.1f}x，"
                     f"任 6m 最大波 {d['max_6m_ratio']:.2f}x")
        lines.append(f"  近 60d 振幅 {e['range_60d']*100:.1f}%，"
                     f"60d 量 {e['vol_ratio']*100:.0f}% × 3y 均量")

    return "\n".join(lines)


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
                r.read()
        except Exception as e:
            print(f"[ERROR] Telegram: {e}", file=sys.stderr)
            all_ok = False
    return all_ok


# ============================================================
# Main
# ============================================================

def main():
    p = argparse.ArgumentParser(description="沉睡巨人篩選器")
    p.add_argument("--min-peak", type=float, default=10.0,
                   help="曾經漲幅倍數門檻 (預設 10x)")
    p.add_argument("--min-pre-peak-years", type=int, default=3,
                   help="峰前需有 N 年資料 (預設 3，避免 Yahoo 起點即峰值的假訊號)")
    p.add_argument("--max-current-pct", type=float, default=0.5,
                   help="現價 / 峰值 ≤ N (預設 0.5 = 跌至少 50%)")
    p.add_argument("--min-years-since-peak", type=int, default=5,
                   help="峰值距今至少 N 年 (預設 5)")
    p.add_argument("--max-5y-ratio", type=float, default=3.0,
                   help="近 5 年最高/最低 < N (預設 3)")
    p.add_argument("--max-6m-ratio", type=float, default=1.5,
                   help="任 120td 滑窗最大/最低 < N (預設 1.5)")
    p.add_argument("--max-60d-range", type=float, default=0.10,
                   help="近 60td 振幅 < N (預設 0.10 = 10%，真正的窄幅整理)")
    p.add_argument("--vol-decline-ratio", type=float, default=0.75,
                   help="近 60d 量 / 3y 平均量 ≤ N (預設 0.75，台股實證 30% 太嚴)")
    p.add_argument("--universe", default="all",
                   help="all / concepts / 逗號代號")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--bot-token", default=os.environ.get("TG_BOT_TOKEN", ""))
    p.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()

    universe = load_universe(args.universe)
    if not args.quiet:
        print(f"📡 Universe: {len(universe)} 檔", file=sys.stderr)
        print(f"門檻: 峰值≥{args.min_peak}x / 跌≥{(1-args.max_current_pct)*100:.0f}% / "
              f"距今≥{args.min_years_since_peak}y / 5y最大{args.max_5y_ratio}x / "
              f"6m最大{args.max_6m_ratio}x / 60d振幅<{args.max_60d_range*100:.0f}% / "
              f"60d量≤{args.vol_decline_ratio*100:.0f}%×3y", file=sys.stderr)

    counts = {"start": len(universe), "A": 0, "AB": 0, "ABC": 0, "ABCD": 0, "ABCDE": 0}
    import threading
    lock = threading.Lock()
    survivors = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, code, name, args, counts, lock): code
                for code, name in universe}
        for fut in as_completed(futs):
            done += 1
            if not args.quiet and done % 100 == 0:
                print(f"  [{done}/{len(universe)}] "
                      f"A:{counts['A']} AB:{counts['AB']} ABC:{counts['ABC']} "
                      f"ABCD:{counts['ABCD']} ABCDE:{counts['ABCDE']}",
                      file=sys.stderr)
            try:
                r = fut.result()
                if r:
                    survivors.append(r)
            except Exception as e:
                if not args.quiet:
                    print(f"  [ERR] {futs[fut]}: {e}", file=sys.stderr)

    report = format_report(survivors, len(universe), counts)
    print(report)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] 需要 --bot-token 或 TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        ok = send_telegram(report, args.bot_token, args.chat_id)
        print(f"\nTelegram: {'✅' if ok else '❌'}", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
強勢股第二波篩選器 (tw_second_wave)

抓「強勢上漲數月 → 1-2 週無法突破 → 急殺 15-25% → 開始反彈」的標的，
搶第二波發動的入場點。

Pattern (參考 2313 華通類似走勢)：
  📈 Phase 1 強勢底盤：峰值前 6 個月已累積大漲 (30%+)
  ⏸️  Phase 2 高點停滯：峰值前後 1-2 週無法再突破新高
  📉 Phase 3 急跌洗盤：1-2 週內急跌 15-25%
  📈 Phase 4 第二波啟動：低點後 1-10 td 開始反彈，量能轉強

七項過濾條件 (各須滿足)：
  F1 強勢底盤  : 峰值前 6m 累積漲幅 ≥ 30% (對應峰前的低點)
  F2 高點在近 : 峰值落在最近 60 td 內，且非今日
  F3 急跌幅度  : peak/trough 跌幅 15-25%
  F4 急跌時長  : peak → trough 5-15 td (太快=異常事件、太慢=慢跌不是急殺)
  F5 已啟動反彈: trough 距今 1-10 td，今日比 trough ≥ +5%
  F6 量能甦醒  : 近 3 日均量 / 急跌期均量 ≥ 1.0 (反彈不能無量)
  F7 還沒突破  : 今日 < 0.98 × peak (避免太晚進場已破前高)

設計動機：強勢股第二波通常是「主力洗籌碼後再拉一波」的高勝率 setup。
Phase 3 急殺把短線散戶洗出去，籌碼鎖定後重新發動。

資料源：Yahoo Finance 6 個月還原日線
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

CACHE_DIR = os.path.join(HERE, "second_wave_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


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
# Universe loader (shared with other tools)
# ============================================================

def load_universe(arg: str) -> list[tuple[str, str]]:
    if "," in arg or arg.isdigit():
        codes = [c.strip() for c in arg.split(",") if c.strip()]
        return [(c, _get_zh_name(c, c)) for c in codes]

    if arg == "all":
        cache_path = os.path.join(HERE, "screener_cache", "universe_all.json")
        if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < 7 * 86400:
            with open(cache_path) as f:
                return [tuple(x) for x in json.load(f)]
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

    if arg == "concepts":
        cpath = os.path.join(HERE, "concept_momentum", "cache", "concepts.json")
        with open(cpath) as f:
            data = json.load(f)
        out, seen = [], set()
        for theme in data.get("themes", {}).values():
            for code in theme.get("stocks", []):
                if code in seen:
                    continue
                seen.add(code)
                out.append((code, _get_zh_name(code, code)))
        return out

    return [(c.strip(), _get_zh_name(c.strip(), c.strip())) for c in arg.split(",") if c.strip()]


# ============================================================
# Yahoo fetcher (cache 1 day for "second wave" — pattern is fast-moving)
# ============================================================

def fetch_yahoo_6mo(code: str) -> dict:
    """Fetch ~9 months daily OHLCV (need 6m+ for rally check, 3m for pattern).
    Cache 1 day. Returns {market, rows: [{ts, close, high, low, volume}, ...]}."""
    today_str = datetime.now().strftime("%Y%m%d")
    cache_path = os.path.join(CACHE_DIR, f"yh_{code}_{today_str}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    end = int(time.time())
    start = end - 270 * 86400  # ~9 months
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
        q = res["indicators"]["quote"][0]
        rows = []
        for i, t in enumerate(ts):
            if q["close"][i] is None:
                continue
            rows.append({
                "ts": int(t),
                "date": datetime.fromtimestamp(t).strftime("%Y-%m-%d"),
                "close": float(q["close"][i]),
                "high": float(q["high"][i] or q["close"][i]),
                "low": float(q["low"][i] or q["close"][i]),
                "volume": int(q["volume"][i] or 0),
            })
        if not rows:
            continue
        out = {"market": market, "rows": rows}
        with open(cache_path, "w") as f:
            json.dump(out, f)
        return out

    with open(cache_path, "w") as f:
        json.dump({}, f)
    return {}


# ============================================================
# Pattern detection
# ============================================================

def detect_second_wave(rows: list[dict], args) -> dict | None:
    """Returns dict of metrics if pattern detected, else None."""
    if len(rows) < 130:
        return None

    # Step 1: find peak in last `peak_lookback` td
    recent = rows[-args.peak_lookback:]
    peak_idx_rel = max(range(len(recent)), key=lambda i: recent[i]["close"])
    peak_idx = len(rows) - args.peak_lookback + peak_idx_rel
    peak = rows[peak_idx]

    # Reject if peak is today / yesterday (still in primary uptrend)
    if peak_idx >= len(rows) - args.min_drop_days:
        return None

    # Step 2: find trough between peak and today
    after_peak = rows[peak_idx + 1:]
    if not after_peak:
        return None
    trough_idx_rel = min(range(len(after_peak)), key=lambda i: after_peak[i]["close"])
    trough_idx = peak_idx + 1 + trough_idx_rel
    trough = rows[trough_idx]

    # Step 3: drop magnitude
    drop_pct = (peak["close"] - trough["close"]) / peak["close"]
    drop_days = trough_idx - peak_idx

    if not (args.drop_min <= drop_pct <= args.drop_max):
        return None
    if not (args.min_drop_days <= drop_days <= args.max_drop_days):
        return None

    # Step 4: pre-peak rally — peak vs 6m before peak min
    rally_lookback = 130
    before_peak = rows[max(0, peak_idx - rally_lookback):peak_idx]
    if len(before_peak) < 60:
        return None  # need at least 3 months pre-peak
    pre_min = min(before_peak, key=lambda r: r["close"])
    rally_gain = (peak["close"] - pre_min["close"]) / pre_min["close"]
    if rally_gain < args.rally_min_gain:
        return None

    # Step 5: recovery — trough within last `max_recovery_days`, today > trough × (1 + min_bounce)
    today = rows[-1]
    days_since_trough = len(rows) - 1 - trough_idx
    if days_since_trough < args.min_recovery_days or days_since_trough > args.max_recovery_days:
        return None

    bounce_pct = (today["close"] - trough["close"]) / trough["close"]
    if bounce_pct < args.recovery_min_gain:
        return None

    # Step 6: volume awakening — last 3 days avg vs drop period avg
    last3_vol = sum(r["volume"] for r in rows[-3:]) / 3
    drop_period = rows[peak_idx:trough_idx + 1]
    drop_avg_vol = sum(r["volume"] for r in drop_period) / max(len(drop_period), 1)
    vol_ratio = last3_vol / max(drop_avg_vol, 1)
    if vol_ratio < args.recovery_vol_ratio:
        return None

    # Step 7: not yet broken peak
    today_vs_peak = today["close"] / peak["close"]
    if today_vs_peak >= args.max_today_vs_peak:
        return None

    return {
        "peak_date": peak["date"],
        "peak_close": peak["close"],
        "trough_date": trough["date"],
        "trough_close": trough["close"],
        "today_close": today["close"],
        "rally_gain": rally_gain,           # pre-peak 6m rally
        "drop_pct": drop_pct,                # peak -> trough
        "drop_days": drop_days,
        "days_since_trough": days_since_trough,
        "bounce_pct": bounce_pct,            # trough -> today
        "vol_ratio": vol_ratio,              # last3 / drop period
        "today_vs_peak": today_vs_peak,
    }


# ============================================================
# Per-stock pipeline
# ============================================================

def process_one(code: str, name: str, args) -> dict | None:
    yh = fetch_yahoo_6mo(code)
    if not yh or not yh.get("rows"):
        return None
    sig = detect_second_wave(yh["rows"], args)
    if not sig:
        return None
    return {
        "code": code,
        "name": name,
        "market": yh.get("market", ""),
        **sig,
    }


# ============================================================
# Output
# ============================================================

def format_report(survivors: list[dict], total: int) -> str:
    lines = []
    lines.append("🌊 強勢股第二波篩選 — 急跌洗盤後即將二度發動")
    lines.append(f"掃描 {total} 檔 → 候選 {len(survivors)} 檔")
    lines.append("")

    if not survivors:
        lines.append("（無符合 pattern 的標的）")
        return "\n".join(lines)

    # Score: 漲幅大 × 急跌深 × 反彈強 × 量能高 × 距離前高還近 (但未破)
    def score(s):
        return (s["rally_gain"] *
                s["drop_pct"] *
                s["bounce_pct"] *
                min(s["vol_ratio"], 3) *
                (s["today_vs_peak"] - 0.7))  # closer to peak = better setup

    survivors.sort(key=score, reverse=True)

    lines.append(f"{'代號':<6}{'名稱':<10}{'前漲':<7}{'跌幅':<7}{'跌天':<5}"
                 f"{'反彈':<7}{'反彈天':<6}{'今/峰':<6}{'量比':<6}{'峰日':<11}")
    lines.append("-" * 80)
    for s in survivors:
        lines.append(
            f"{s['code']:<6}{s['name'][:8]:<10}"
            f"{s['rally_gain']*100:>4.0f}%   "
            f"{s['drop_pct']*100:>4.1f}%   "
            f"{s['drop_days']:<5}"
            f"{s['bounce_pct']*100:>+4.1f}%   "
            f"{s['days_since_trough']:<6}"
            f"{s['today_vs_peak']*100:>4.0f}% "
            f"{s['vol_ratio']:>4.1f}x "
            f"{s['peak_date']:<11}"
        )

    # Detail blocks for top 20
    lines.append("")
    for s in survivors[:20]:
        lines.append(f"\n{s['code']} {s['name']} [{s['market']}]")
        lines.append(f"  Phase 1 強勢底盤：峰前 6m 漲幅 {s['rally_gain']*100:.0f}%")
        lines.append(f"  Phase 2 峰值：{s['peak_date']} 收 {s['peak_close']:.1f}")
        lines.append(f"  Phase 3 急跌：{s['drop_days']} td 跌 {s['drop_pct']*100:.1f}% 至 "
                     f"{s['trough_date']} 收 {s['trough_close']:.1f}")
        lines.append(f"  Phase 4 反彈：低點後 {s['days_since_trough']} td，今價 {s['today_close']:.1f}"
                     f" = trough +{s['bounce_pct']*100:.1f}% / 峰值 {s['today_vs_peak']*100:.0f}%")
        lines.append(f"  量能：近 3d 均量 / 急跌期均量 = {s['vol_ratio']:.2f}x")

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
    p = argparse.ArgumentParser(description="強勢股第二波篩選器")
    # Phase 1 — pre-peak rally
    p.add_argument("--rally-min-gain", type=float, default=0.30,
                   help="峰前 6m 累積漲幅 ≥ N (預設 0.30)")
    # Phase 2 — peak in recent
    p.add_argument("--peak-lookback", type=int, default=60,
                   help="峰值落在最近 N td 內 (預設 60，~3 個月)")
    # Phase 3 — drop
    p.add_argument("--drop-min", type=float, default=0.15,
                   help="急跌幅度下限 (預設 0.15)")
    p.add_argument("--drop-max", type=float, default=0.25,
                   help="急跌幅度上限 (預設 0.25)")
    p.add_argument("--min-drop-days", type=int, default=5,
                   help="急跌持續至少 N td (預設 5)")
    p.add_argument("--max-drop-days", type=int, default=15,
                   help="急跌持續最多 N td (預設 15，超過視為慢跌)")
    # Phase 4 — recovery
    p.add_argument("--min-recovery-days", type=int, default=1,
                   help="低點距今至少 N td (預設 1，避免今日才見底)")
    p.add_argument("--max-recovery-days", type=int, default=10,
                   help="低點距今最多 N td (預設 10，太久反彈已老)")
    p.add_argument("--recovery-min-gain", type=float, default=0.05,
                   help="今日 vs trough 漲幅 ≥ N (預設 0.05)")
    p.add_argument("--recovery-vol-ratio", type=float, default=0.7,
                   help="近 3d 均量 / 急跌期均量 ≥ N (預設 0.7，急跌期常爆恐慌量，"
                        "反彈初期不需要也爆量，只要量沒萎縮)")
    p.add_argument("--max-today-vs-peak", type=float, default=0.98,
                   help="今日 / 峰值 < N (預設 0.98，避免已破前高才追)")

    p.add_argument("--universe", default="all", help="all / concepts / 逗號代號")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--bot-token", default=os.environ.get("TG_BOT_TOKEN", ""))
    p.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()

    universe = load_universe(args.universe)
    if not args.quiet:
        print(f"📡 Universe: {len(universe)} 檔", file=sys.stderr)
        print(f"參數: 漲幅≥{args.rally_min_gain*100:.0f}% / "
              f"跌{args.drop_min*100:.0f}-{args.drop_max*100:.0f}% / "
              f"跌天{args.min_drop_days}-{args.max_drop_days} / "
              f"反彈天{args.min_recovery_days}-{args.max_recovery_days} / "
              f"量比≥{args.recovery_vol_ratio} / "
              f"今/峰<{args.max_today_vs_peak}", file=sys.stderr)

    survivors = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_one, code, name, args): code
                for code, name in universe}
        for fut in as_completed(futs):
            done += 1
            if not args.quiet and done % 100 == 0:
                print(f"  [{done}/{len(universe)}] 候選 {len(survivors)}",
                      file=sys.stderr)
            try:
                r = fut.result()
                if r:
                    survivors.append(r)
            except Exception as e:
                if not args.quiet:
                    print(f"  [ERR] {futs[fut]}: {e}", file=sys.stderr)

    report = format_report(survivors, len(universe))
    print(report)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] 需要 --bot-token 或 TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        ok = send_telegram(report, args.bot_token, args.chat_id)
        print(f"\nTelegram: {'✅' if ok else '❌'}", file=sys.stderr)


if __name__ == "__main__":
    main()

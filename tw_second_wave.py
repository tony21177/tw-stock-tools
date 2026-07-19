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
import bisect
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

# 偵測參數單一來源 — argparse 與回測共用（勿在他處手抄預設值）
FILTER_DEFAULTS = dict(
    rally_min_gain=0.30, peak_lookback=60, drop_min=0.15, drop_max=0.25,
    min_drop_days=5, max_drop_days=15, min_recovery_days=1,
    max_recovery_days=10, recovery_min_gain=0.05, recovery_vol_ratio=0.7,
    max_today_vs_peak=0.98,
)

# 分層標記 (2026-07-07 子群分析, 詳 README「子群分析」節): 不改篩選、只標層
TIER_BIG_TURNOVER_NTD = 1_100_000_000   # 20d 均成交額門檻 (~P67)
TIER_EARLY_TVP = 0.88                    # 距前高門檻 (today/peak < 0.88 = 反彈早期)


def classify_tier(today_vs_peak: float, turn20_ntd: float) -> str:
    """⭐ 早期+大額 / ◐ 早期 / ▽ 已近前高 — 依 2026-07 子群分析分層。"""
    if today_vs_peak < TIER_EARLY_TVP:
        return "⭐" if turn20_ntd >= TIER_BIG_TURNOVER_NTD else "◐"
    return "▽"


# 借券急跌變化標記 (2026-07-09, episode 條件化回測, 詳 README「籌碼確認」節):
# 急跌期 (peak_date→trough_date) 借券賣出餘額變化 (%)，標記非濾網
SBL_TAG_DROP = -5.0   # ≤ -5% = 回補 (空方撤退, 洗盤跡象)
SBL_TAG_RISE = 5.0    # ≥ +5% = 增加 (空方加碼, 跨年較穩的避開訊號)


def classify_sbl_tag(sbl_chg_pct):
    """急跌期借券賣餘變化 → 借↓(空方回補=洗盤跡象) / 借↑(空方加碼=避開) / —。None → —。"""
    if sbl_chg_pct is None:
        return "—"
    if sbl_chg_pct <= SBL_TAG_DROP:
        return "借↓"
    if sbl_chg_pct >= SBL_TAG_RISE:
        return "借↑"
    return "—"

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
    Cache 1 day. Returns {market, rows: [{date, close, high, low, volume}, ...]}

    Migrated 2026-05-11 from Yahoo Finance to FinMind TaiwanStockPrice.
    Function name kept for backwards compatibility; data source is now FinMind.
    Raw close (FinMind) is correct for pattern detection — no dividend adjustment.
    """
    today_str = datetime.now().strftime("%Y%m%d")
    cache_path = os.path.join(CACHE_DIR, f"yh_{code}_{today_str}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        with open(cache_path, "w") as f:
            json.dump({}, f)
        return {}

    end = datetime.now()
    start = end - timedelta(days=270)  # ~9 months
    sys.path.insert(0, HERE)
    import finmind_client  # noqa: F811

    rows = []
    market = ""
    try:
        raw = finmind_client.fetch_stock_price(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token)
    except Exception as ex:
        print(f"[WARN] FinMind fetch {code}: {ex}", file=sys.stderr)
        with open(cache_path, "w") as f:
            json.dump({}, f)
        return {}

    if not raw:
        with open(cache_path, "w") as f:
            json.dump({}, f)
        return {}

    # Determine market from stock_id suffix convention:
    # TWSE (上市) stocks have numeric codes; TPEx (上櫃) detection via FinMind
    # data itself doesn't carry exchange — try 上市 first, fall back to 上櫃.
    # In practice, process_one() only uses market for display; keep it simple.
    market = "上市"

    for r in raw:
        if r.get("close") is None or float(r.get("close", 0)) <= 0:
            continue
        rows.append({
            "date": r["date"],                          # YYYY-MM-DD
            "close": float(r["close"]),
            "high": float(r.get("max", r["close"])),
            "low": float(r.get("min", r["close"])),
            "volume": int(r.get("Trading_Volume", 0)),
        })

    if not rows:
        with open(cache_path, "w") as f:
            json.dump({}, f)
        return {}

    out = {"market": market, "rows": rows}
    with open(cache_path, "w") as f:
        json.dump(out, f)
    return out


def _ex_dates_cached(code: str, token: str) -> list[str]:
    """快取 7 天避免每天 3000 次呼叫。"""
    p = os.path.join(CACHE_DIR, f"div_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        with open(p) as f:
            return json.load(f)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import finmind_client
    start = (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d")
    ex = finmind_client.fetch_dividend_ex_dates(code, start, token)
    with open(p, "w") as f:
        json.dump(ex, f)
    return ex


def _sbl_chg_cached(code: str, peak_date: str, trough_date: str) -> float | None:
    """急跌期 (peak_date→trough_date) 借券賣出餘額變化 % — fail-open (任何錯誤 → None)。

    cache 存原始 series（當日 TTL），每檔 1 次 FinMind 呼叫。
    bal@X = 日期 ≤ X 的最後一筆 SBLShortSalesCurrentDayBalance；
    bal@peak ≤ 0 或資料缺 → None（避免除以 0 / 無意義變化率）。
    """
    today_str = datetime.now().strftime("%Y%m%d")
    cache_path = os.path.join(CACHE_DIR, f"sbl_{code}_{today_str}.json")
    series = None
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                series = json.load(f)
        except Exception:
            series = None
    if series is None:
        token = os.environ.get("FINMIND_TOKEN", "")
        if not token:
            return None
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import finmind_client
            start = (datetime.strptime(peak_date, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            raw = finmind_client.fetch_short_sale_balances(code, start, end, token)
            series = [{"date": r.get("date", ""),
                       "balance": r.get("SBLShortSalesCurrentDayBalance")}
                      for r in raw if r.get("date")]
            with open(cache_path, "w") as f:
                json.dump(series, f)
        except Exception as e:
            print(f"[WARN] sbl fetch {code}: {e}", file=sys.stderr)
            return None

    try:
        dates = sorted(r["date"] for r in series)
        by_date = {r["date"]: r.get("balance") for r in series}

        def _bal_at(target: str):
            idx = bisect.bisect_right(dates, target) - 1
            if idx < 0:
                return None
            return by_date.get(dates[idx])

        bal_peak = _bal_at(peak_date)
        bal_trough = _bal_at(trough_date)
        if bal_peak is None or bal_trough is None:
            return None
        bal_peak = float(bal_peak)
        bal_trough = float(bal_trough)
        if bal_peak <= 0:
            return None
        return (bal_trough / bal_peak - 1) * 100
    except Exception:
        return None


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
    # 除權息 guard：peak→今日 之間有除權息交易日 → 急跌可能是除權缺口，剔除
    token = os.environ.get("FINMIND_TOKEN", "")
    if token:
        try:
            ex = _ex_dates_cached(code, token)      # 新 helper，見下
            if any(sig["peak_date"] <= d <= yh["rows"][-1]["date"] for d in ex):
                return None
        except Exception as e:
            print(f"[WARN] dividend guard {code}: {e}", file=sys.stderr)
    rows = yh["rows"]
    last20 = rows[-20:]
    turn20_ntd = sum(r["volume"] * r["close"] for r in last20) / max(len(last20), 1)
    tier = classify_tier(sig["today_vs_peak"], turn20_ntd)
    sbl_chg = _sbl_chg_cached(code, sig["peak_date"], sig["trough_date"])
    sbl_tag = classify_sbl_tag(sbl_chg)
    return {"code": code, "name": name, "market": yh.get("market", ""), **sig,
            "turn20_ntd": turn20_ntd, "tier": tier,
            "sbl_chg": sbl_chg, "sbl_tag": sbl_tag}


# ============================================================
# Output
# ============================================================

def format_report(survivors: list[dict], total: int) -> str:
    lines = []
    lines.append("🌊 強勢股第二波篩選 — 急跌洗盤後即將二度發動")
    lines.append(f"掃描 {total} 檔 → 候選 {len(survivors)} 檔")
    lines.append(
        "⚠ 回測(2026-07): 20日持有型 setup, 對同日基準有 edge 但中位數為負(樂透型) — "
        "單檔部位宜小、分散。詳 /second-wave-backtest"
    )
    lines.append("")

    if not survivors:
        lines.append("（無符合 pattern 的標的）")
        return "\n".join(lines)

    # Score 保留供 JSON 相容（回測已證 IC≈0，無鑑別力，不再用於排序）
    def score(s):
        return (s["rally_gain"] *
                s["drop_pct"] *
                s["bounce_pct"] *
                min(s["vol_ratio"], 3) *
                (s["today_vs_peak"] - 0.7))  # closer to peak = better setup

    # 排序改依 today_vs_peak 升冪（越早期越前面）— 詳 README「子群分析」節
    survivors.sort(key=lambda s: s["today_vs_peak"])

    lines.append(
        "⭐ 早期(<88%)+大額(≥11億/日)  ◐ 早期  ▽ 已近前高 — "
        "依 2026-07 子群回測，⭐ 組 20d 超額 +11.9%、▽ 組 ≈0"
    )
    lines.append(
        "借↓ 空方回補(洗盤跡象, 動能市 +6.5%) 借↑ 空方加碼(跨年避開訊號, 2022 年 -5.9%)"
    )
    lines.append(f"{'層':<3}{'借':<4}{'代號':<6}{'名稱':<10}{'前漲':<7}{'跌幅':<7}{'跌天':<5}"
                 f"{'反彈':<7}{'反彈天':<6}{'今/峰':<6}{'量比':<6}{'峰日':<11}")
    lines.append("-" * 80)
    for s in survivors:
        lines.append(
            f"{s.get('tier', ''):<3}"
            f"{s.get('sbl_tag', '—'):<4}"
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
        lines.append(f"\n{s.get('tier', '')} {s['code']} {s['name']} [{s['market']}]")
        lines.append(f"  Phase 1 強勢底盤：峰前 6m 漲幅 {s['rally_gain']*100:.0f}%")
        lines.append(f"  Phase 2 峰值：{s['peak_date']} 收 {s['peak_close']:.1f}")
        lines.append(f"  Phase 3 急跌：{s['drop_days']} td 跌 {s['drop_pct']*100:.1f}% 至 "
                     f"{s['trough_date']} 收 {s['trough_close']:.1f}")
        sbl_chg = s.get("sbl_chg")
        sbl_str = "—" if sbl_chg is None else f"{sbl_chg:+.1f}%"
        lines.append(f"  籌碼：急跌期借券賣餘變化 {sbl_str} [{s.get('sbl_tag', '—')}]")
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
    p.add_argument("--rally-min-gain", type=float, default=FILTER_DEFAULTS["rally_min_gain"],
                   help="峰前 6m 累積漲幅 ≥ N (預設 0.30)")
    # Phase 2 — peak in recent
    p.add_argument("--peak-lookback", type=int, default=FILTER_DEFAULTS["peak_lookback"],
                   help="峰值落在最近 N td 內 (預設 60，~3 個月)")
    # Phase 3 — drop
    p.add_argument("--drop-min", type=float, default=FILTER_DEFAULTS["drop_min"],
                   help="急跌幅度下限 (預設 0.15)")
    p.add_argument("--drop-max", type=float, default=FILTER_DEFAULTS["drop_max"],
                   help="急跌幅度上限 (預設 0.25)")
    p.add_argument("--min-drop-days", type=int, default=FILTER_DEFAULTS["min_drop_days"],
                   help="急跌持續至少 N td (預設 5)")
    p.add_argument("--max-drop-days", type=int, default=FILTER_DEFAULTS["max_drop_days"],
                   help="急跌持續最多 N td (預設 15，超過視為慢跌)")
    # Phase 4 — recovery
    p.add_argument("--min-recovery-days", type=int, default=FILTER_DEFAULTS["min_recovery_days"],
                   help="低點距今至少 N td (預設 1，避免今日才見底)")
    p.add_argument("--max-recovery-days", type=int, default=FILTER_DEFAULTS["max_recovery_days"],
                   help="低點距今最多 N td (預設 10，太久反彈已老)")
    p.add_argument("--recovery-min-gain", type=float, default=FILTER_DEFAULTS["recovery_min_gain"],
                   help="今日 vs trough 漲幅 ≥ N (預設 0.05)")
    p.add_argument("--recovery-vol-ratio", type=float, default=FILTER_DEFAULTS["recovery_vol_ratio"],
                   help="近 3d 均量 / 急跌期均量 ≥ N (預設 0.7，急跌期常爆恐慌量，"
                        "反彈初期不需要也爆量，只要量沒萎縮)")
    p.add_argument("--max-today-vs-peak", type=float, default=FILTER_DEFAULTS["max_today_vs_peak"],
                   help="今日 / 峰值 < N (預設 0.98，避免已破前高才追)")

    p.add_argument("--universe", default="all", help="all / concepts / 逗號代號")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--json-out", help="將今日候選寫到 JSON 路徑（dashboard 用）")
    p.add_argument("--bot-token", default=os.environ.get("TG_BOT_TOKEN", ""))
    p.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    p.add_argument("--line-to", help="LINE 收件者 ID (U=個人/C=群組，逗號分隔多個)；"
                                     "憑證用 env LINE_CHANNEL_TOKEN 或 "
                                     "LINE_CHANNEL_ID+LINE_CHANNEL_SECRET")
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

    if args.json_out:
        import os as _os
        _os.makedirs(_os.path.dirname(_os.path.abspath(args.json_out)) or ".", exist_ok=True)
        from datetime import datetime as _dt
        with open(args.json_out, "w") as _f:
            json.dump({
                "date": _dt.now().strftime("%Y%m%d"),
                "candidates": [
                    {
                        "code": c.get("code", ""),
                        "name": c.get("name", c.get("code", "")),
                        "second_wave_score": round(
                            c.get("rally_gain", 0.0) *
                            c.get("drop_pct", 0.0) *
                            c.get("bounce_pct", 0.0) *
                            min(c.get("vol_ratio", 0.0), 3) *
                            (c.get("today_vs_peak", 0.7) - 0.7),
                            4,
                        ),
                        "drop_pct": round(c.get("drop_pct", 0.0), 4),
                        "volume_ratio": round(c.get("vol_ratio", 0.0), 2),
                        "tier": c.get("tier", ""),
                        "today_vs_peak": round(c.get("today_vs_peak", 0.0), 4),
                        "turn20_m": round(c.get("turn20_ntd", 0.0) / 1_000_000, 1),
                        "sbl_tag": c.get("sbl_tag", "—"),
                        "sbl_chg_pct": (
                            round(c["sbl_chg"], 1) if c.get("sbl_chg") is not None else None
                        ),
                    } for c in survivors
                ],
            }, _f, ensure_ascii=False, indent=2)
        print(f"[second_wave] wrote {args.json_out}", file=sys.stderr)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] 需要 --bot-token 或 TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        ok = send_telegram(report, args.bot_token, args.chat_id)
        print(f"\nTelegram: {'✅' if ok else '❌'}", file=sys.stderr)

    if args.line_to:
        import line_push
        token = line_push.resolve_token()
        if not token:
            print("[ERROR] LINE 憑證未設定/換發失敗 (LINE_CHANNEL_TOKEN 或 "
                  "LINE_CHANNEL_ID+LINE_CHANNEL_SECRET)", file=sys.stderr)
        else:
            for rcpt in [r.strip() for r in args.line_to.split(",")
                         if r.strip()]:
                ok = line_push.push_text(report, token, rcpt)
                print(f"LINE → {rcpt[:6]}…: {'✅' if ok else '❌'}",
                      file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
漲停日訊號回測 (tw_limitup_signal)

掃描今日漲停 (close 漲幅 ≥ 9.5%) 的個股，回看前一個交易日的四項訊號，
快速辨識「事後可從前日籌碼預判」vs「純突發拉抬」的漲停。

四項訊號 (各 1 分):
  A 漲停接力: 前日收盤漲幅 ≥ +5% 或前日已漲停
  B 借券回補: 借券賣出餘額連續走低 (3d avg / prior 5d avg < 0.97)
  C 籌碼集中: 7 天累積外資/主力買超 (top10 中至少 2 家外資淨買, 且
              買超 top5 合計 > 賣超 top5 合計)
  D 量能蓄勢: 前日成交量 / 20 日均量 ≥ 1.0

輸出:
  4/4 全訊號 → 詳細
  3/4       → 詳細
  2/4       → 一行摘要
  ≤1/4      → 僅列代碼/名稱

資料來源:
  漲停清單   : TWSE MI_INDEX (上市) + TPEx OpenAPI (上櫃)
  OHLCV     : Yahoo Finance (.TW / .TWO)
  借券賣出餘額: FinMind TaiwanDailyShortSaleBalances (data_id 可用 register tier)
  分點 7 天累積: HiStock branch.aspx (爬蟲)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import gzip
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
try:
    from stock_names import get_name as _get_zh_name
except Exception:
    def _get_zh_name(code, fallback=""):
        return fallback or code

CACHE_DIR = os.path.join(HERE, "limitup_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
HISTOCK_URL = "https://histock.tw/stock/branch.aspx?no={code}&day={days}"

# Foreign-broker name fragments (HiStock label patterns)
FOREIGN_KEYS = [
    "高盛", "摩根士丹利", "摩根大通", "JPM", "瑞銀", "野村", "花旗",
    "美林", "麥格理", "港商", "新加坡商", "美商", "亞洲", "里昂",
    "巴克萊", "瑞士信貸", "德意志",
]


# ============================================================
# HTTP helpers
# ============================================================

def http_json(url: str, retries: int = 2, headers: dict = None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
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


def http_text(url: str, retries: int = 2) -> str:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return ""
    return ""


# ============================================================
# Step 1: find today's limit-up stocks (TWSE + TPEx)
# ============================================================

TWSE_MI_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={ymd}&type=ALLBUT0999"
TPEX_OPENAPI = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TPEX_LEGACY = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_d}&se=EW&s=0,asc,0"


def _fetch_url_bytes(url: str, retries: int = 2) -> bytes:
    """GET url with curl-like compression handling. Returns raw bytes."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return b""
    return b""


def _fetch_url_curl(url: str) -> bytes:
    """Fallback to curl for endpoints that send chunked-gzip (like TPEx OpenAPI)."""
    import subprocess
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "--max-time", "60",
             "-H", f"User-Agent: {UA}", url],
            capture_output=True, timeout=120,
        )
        return r.stdout or b""
    except Exception:
        return b""


def fetch_twse_quotes(target_date: str) -> list[dict]:
    """target_date: YYYY-MM-DD. Returns normalized rows."""
    ymd = target_date.replace("-", "")
    url = TWSE_MI_URL.format(ymd=ymd)
    raw = _fetch_url_bytes(url)
    if not raw:
        return []
    try:
        d = json.loads(raw.decode())
    except Exception:
        return []
    if d.get("stat") != "OK":
        return []
    tables = d.get("tables", [])
    target = None
    for t in tables:
        if "每日收盤行情" in t.get("title", "") and t.get("fields"):
            target = t
            break
    if not target:
        return []
    fields = target["fields"]
    try:
        i_code = fields.index("證券代號")
        i_name = fields.index("證券名稱")
        i_open = fields.index("開盤價")
        i_close = fields.index("收盤價")
        i_sign = fields.index("漲跌(+/-)")
        i_spread = fields.index("漲跌價差")
        i_volume = fields.index("成交股數")
    except ValueError:
        return []
    out = []
    for row in target["data"]:
        try:
            code = str(row[i_code]).strip()
            name = str(row[i_name]).strip()
            close = float(str(row[i_close]).replace(",", ""))
            open_ = float(str(row[i_open]).replace(",", "")) if row[i_open] else 0.0
            spread = float(str(row[i_spread]).replace(",", ""))
            volume = int(str(row[i_volume]).replace(",", ""))
            sign_s = str(row[i_sign]).lower()
            sign = 1 if ("red" in sign_s or sign_s.strip() == "+") else (-1 if ("green" in sign_s or sign_s.strip() == "-") else 0)
        except (ValueError, IndexError, TypeError):
            continue
        out.append({
            "code": code, "name": name, "open": open_, "close": close,
            "spread": spread, "sign": sign, "volume": volume, "market": "上市",
        })
    return out


def fetch_tpex_quotes(target_date: str) -> list[dict]:
    """target_date: YYYY-MM-DD. Uses OpenAPI for today, legacy URL for past dates."""
    today = datetime.now().strftime("%Y-%m-%d")
    raw = b""
    if target_date == today:
        raw = _fetch_url_curl(TPEX_OPENAPI)
    if not raw:
        # Fallback to legacy URL with ROC date
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        roc_d = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
        raw = _fetch_url_curl(TPEX_LEGACY.format(roc_d=roc_d))
    if not raw:
        return []
    try:
        d = json.loads(raw.decode())
    except Exception:
        return []
    out = []
    if isinstance(d, list):
        # OpenAPI format
        for r in d:
            try:
                code = str(r.get("SecuritiesCompanyCode") or "").strip()
                name = str(r.get("CompanyName") or "").strip()
                close = float(str(r.get("Close") or "0").replace(",", ""))
                open_ = float(str(r.get("Open") or "0").replace(",", ""))
                chg = float(str(r.get("Change") or "0").replace("+", "").replace(",", ""))
                vol = int(str(r.get("TradingShares") or "0").replace(",", ""))
            except (ValueError, TypeError):
                continue
            sign = 1 if chg > 0 else (-1 if chg < 0 else 0)
            spread = abs(chg)
            out.append({
                "code": code, "name": name, "open": open_, "close": close,
                "spread": spread, "sign": sign, "volume": vol, "market": "上櫃",
            })
    elif isinstance(d, dict) and d.get("aaData"):
        # Legacy format: list of lists
        # 欄位: 代號 名稱 收盤 漲跌 開盤 最高 最低 ...
        for row in d.get("aaData", []):
            try:
                code = str(row[0]).strip()
                name = str(row[1]).strip()
                close = float(str(row[2]).replace(",", ""))
                chg = float(str(row[3]).replace("+", "").replace("---", "0").replace(",", ""))
                open_ = float(str(row[4]).replace(",", "")) if row[4] not in ("---", "") else 0.0
                vol = int(str(row[8]).replace(",", "")) if len(row) > 8 else 0
            except (ValueError, IndexError, TypeError):
                continue
            sign = 1 if chg > 0 else (-1 if chg < 0 else 0)
            spread = abs(chg)
            out.append({
                "code": code, "name": name, "open": open_, "close": close,
                "spread": spread, "sign": sign, "volume": vol, "market": "上櫃",
            })
    return out


def fetch_market_quotes(target_date: str, token: str = "") -> list[dict]:
    """Combined TWSE + TPEx daily quotes. Cached 1 day."""
    cache_path = os.path.join(CACHE_DIR, f"market_{target_date}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
    rows = fetch_twse_quotes(target_date) + fetch_tpex_quotes(target_date)
    if rows:
        with open(cache_path, "w") as f:
            json.dump(rows, f)
    return rows


def find_limitup(rows: list[dict], min_pct: float = 9.5) -> list[dict]:
    """Filter limit-up stocks. Returns list of {code, name, close, change_pct, volume, market}."""
    results = []
    for r in rows:
        code = r.get("code", "")
        if not re.fullmatch(r"\d{4}", code):
            continue
        if r.get("sign", 0) <= 0:
            continue
        close = r.get("close", 0)
        spread = r.get("spread", 0)
        if close <= 0 or spread <= 0:
            continue
        prev = close - spread
        if prev <= 0:
            continue
        pct = spread / prev * 100
        if pct >= min_pct:
            zh_name = _get_zh_name(code, r.get("name", code))
            results.append({
                "code": code,
                "name": zh_name,
                "close": close,
                "change_pct": pct,
                "volume": r.get("volume", 0),
                "market": r.get("market", ""),
            })
    results.sort(key=lambda x: -x["change_pct"])
    return results


# ============================================================
# Step 2: per-stock signal data
# ============================================================

def fetch_price_history(code: str, target_date: str, token: str = "") -> list[dict]:
    """Fetch ~50 trading days ending target_date via Yahoo. Cached by date.
    Tries .TW first then .TWO. Returns list of dicts with keys date/open/close/volume."""
    cache_path = os.path.join(CACHE_DIR, f"px_{code}_{target_date}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    rows = []
    for suffix in (".TW", ".TWO"):
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}"
               f"?range=3mo&interval=1d")
        d = http_json(url)
        try:
            r = d["chart"]["result"][0]
            ts = r["timestamp"]
            q = r["indicators"]["quote"][0]
        except (KeyError, IndexError, TypeError):
            continue
        if not ts:
            continue
        for i, t in enumerate(ts):
            try:
                rows.append({
                    "date": datetime.fromtimestamp(t).strftime("%Y-%m-%d"),
                    "open": q["open"][i],
                    "high": q["high"][i],
                    "low": q["low"][i],
                    "close": q["close"][i],
                    "volume": q["volume"][i],
                })
            except (KeyError, IndexError, TypeError):
                continue
        if rows:
            break
    # Trim to <= target_date
    rows = [r for r in rows if r["date"] <= target_date and r["close"]]
    with open(cache_path, "w") as f:
        json.dump(rows, f)
    return rows


def fetch_short_balance(code: str, target_date: str, token: str = "") -> list[dict]:
    """Fetch 借券賣出餘額 (SBLShortSalesCurrentDayBalance) up to target_date.
    Cached by date. Returns ascending list of {date, balance}."""
    cache_path = os.path.join(CACHE_DIR, f"sbl_{code}_{target_date}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    end = target_date
    start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "dataset": "TaiwanDailyShortSaleBalances",
        "data_id": code,
        "start_date": start,
        "end_date": end,
    })
    url = f"https://api.finmindtrade.com/api/v4/data?{params}"
    if token:
        url += f"&token={token}"
    data = http_json(url)
    rows = (data or {}).get("data", []) or []
    out = []
    for r in rows:
        try:
            out.append({
                "date": r["date"],
                "balance": int(r.get("SBLShortSalesCurrentDayBalance") or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda x: x["date"])
    with open(cache_path, "w") as f:
        json.dump(out, f)
    return out


def fetch_histock_7d(code: str, target_date: str) -> dict:
    """Fetch HiStock 7-day branch summary. Cached by date."""
    cache_path = os.path.join(CACHE_DIR, f"hi7_{code}_{target_date}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    html = http_text(HISTOCK_URL.format(code=code, days=7))
    if not html:
        with open(cache_path, "w") as f:
            json.dump({"buyers": [], "sellers": []}, f)
        return {"buyers": [], "sellers": []}

    # Reuse parsing from tw_broker_history_lookup
    sys.path.insert(0, HERE)
    from tw_broker_history_lookup import parse_branch_page
    parsed = parse_branch_page(html)
    out = {
        "buyers": [(n, bv, sv, net, avg) for (n, bv, sv, net, avg) in parsed.get("buyers", [])],
        "sellers": [(n, bv, sv, net, avg) for (n, bv, sv, net, avg) in parsed.get("sellers", [])],
    }
    with open(cache_path, "w") as f:
        json.dump(out, f)
    return out


# ============================================================
# Step 3: signal scoring
# ============================================================

def signal_a_relay(px: list[dict]) -> tuple[bool, str]:
    """A 漲停接力: 過去 3 日 (不含今日) 任一日漲幅 ≥ +5%
    且前日收盤未跌破其開盤 4% 以上 (沒有黑K崩盤)。"""
    # px ascending; last is today (the limit-up day). px[-2] = prior trading day.
    if len(px) < 5:
        return False, "(資料不足)"
    # Check last 3 days (excluding today)
    gains = []
    for i in (-2, -3, -4):
        if abs(i) >= len(px):
            break
        c = px[i]["close"]
        prev = px[i - 1]["close"] if abs(i - 1) <= len(px) else 0
        if prev > 0 and c > 0:
            gains.append((i, (c - prev) / prev * 100))
    if not gains:
        return False, "(無前日)"
    max_gain = max(g for _, g in gains)
    # Veto if prior-day collapsed
    prev_open = px[-2].get("open") or px[-2]["close"]
    prev_close = px[-2]["close"]
    if prev_open > 0:
        intraday = (prev_close - prev_open) / prev_open * 100
        if intraday <= -4.0:
            return False, f"前日盤中崩 {intraday:.1f}%"
    if max_gain >= 9.5:
        return True, f"近 3 日內漲停 +{max_gain:.1f}%"
    if max_gain >= 5.0:
        return True, f"近 3 日強勢 +{max_gain:.1f}%"
    return False, f"近 3 日最大 {max_gain:+.1f}%"


def signal_b_short_cover(sbl: list[dict]) -> tuple[bool, str]:
    """B 借券回補: 3d avg / prior 5d avg ≤ 0.97 OR 前日單日 ≤ -3%."""
    if len(sbl) < 8:
        return False, "(資料不足)"
    recent = sbl[-3:]
    prior = sbl[-8:-3]
    avg_r = sum(r["balance"] for r in recent) / 3
    avg_p = sum(r["balance"] for r in prior) / 5
    if avg_p <= 0:
        return False, "(無前期均量)"
    ratio = avg_r / avg_p
    last_chg = (sbl[-1]["balance"] - sbl[-2]["balance"]) / max(sbl[-2]["balance"], 1) * 100
    if ratio <= 0.97:
        return True, f"借券賣餘 -{(1-ratio)*100:.1f}% (前日{last_chg:+.1f}%)"
    if last_chg <= -3.0:
        return True, f"前日借券賣餘 {last_chg:+.1f}% (3d/5d {(ratio-1)*100:+.1f}%)"
    return False, f"借券賣餘 {(ratio-1)*100:+.1f}% (前日{last_chg:+.1f}%)"


def signal_c_chip_concentration(broker: dict) -> tuple[bool, str]:
    """C 籌碼集中: top10 buyers 中外資 ≥ 2 家 (淨買為正)。
    或: top5 買超合計 ≥ top5 賣超合計 (買方更集中)。"""
    buyers = broker.get("buyers", [])
    sellers = broker.get("sellers", [])
    if not buyers:
        return False, "(無籌碼)"

    foreign_count = 0
    foreign_names = []
    for b in buyers[:10]:
        name = b[0]
        if any(k in name for k in FOREIGN_KEYS):
            foreign_count += 1
            foreign_names.append(name.split("-")[0][:6])

    top5_buy = sum(b[3] for b in buyers[:5]) if buyers else 0
    top5_sell = sum(abs(s[3]) for s in sellers[:5]) if sellers else 0

    ok_foreign = foreign_count >= 2
    ok_dominance = top5_buy >= top5_sell

    msg_f = f"外資 {foreign_count} 家" + (f" ({','.join(foreign_names[:3])})" if foreign_names else "")
    msg_d = f"買{top5_buy:,}/賣{top5_sell:,}"
    if ok_foreign or ok_dominance:
        return True, f"{msg_f} {msg_d}"
    return False, f"{msg_f} {msg_d}"


def signal_d_volume(px: list[dict]) -> tuple[bool, str]:
    """D 量能蓄勢: 前日量 / 20d 均量 ≥ 1.0
    或前日量 / 60d 均量 ≥ 1.5 (避免被近期瞬間爆量拉高均線)。"""
    if len(px) < 22:
        return False, "(資料不足)"
    prev_vol = px[-2].get("volume") or 0
    avg20 = sum((r.get("volume") or 0) for r in px[-22:-2]) / 20
    if avg20 <= 0:
        return False, "(無均量)"
    ratio20 = prev_vol / avg20

    avg60 = avg20
    ratio60 = ratio20
    if len(px) >= 62:
        avg60 = sum((r.get("volume") or 0) for r in px[-62:-2]) / 60
        if avg60 > 0:
            ratio60 = prev_vol / avg60

    if ratio20 >= 1.0:
        return True, f"前日量 {ratio20:.1f}x 20d / {ratio60:.1f}x 60d"
    if ratio60 >= 1.5:
        return True, f"前日量 {ratio60:.1f}x 60d ({ratio20:.1f}x 20d)"
    return False, f"前日量 {ratio20:.1f}x 20d / {ratio60:.1f}x 60d"


def score_stock(code: str, name: str, target_date: str, token: str,
                quiet: bool = False) -> dict:
    """Compute all 4 signals for a single stock. Returns dict with score and details."""
    if not quiet:
        print(f"  [掃] {code} {name} ...", file=sys.stderr)

    px = fetch_price_history(code, target_date, token)
    sbl = fetch_short_balance(code, target_date, token)
    broker = fetch_histock_7d(code, target_date)

    a_ok, a_msg = signal_a_relay(px)
    b_ok, b_msg = signal_b_short_cover(sbl)
    c_ok, c_msg = signal_c_chip_concentration(broker)
    d_ok, d_msg = signal_d_volume(px)

    score = sum([a_ok, b_ok, c_ok, d_ok])

    # Pull buyers preview
    buyers = broker.get("buyers", [])
    top3_buyers = ", ".join(f"{b[0]}+{b[3]}" for b in buyers[:3]) if buyers else "(無)"

    return {
        "code": code,
        "name": name,
        "score": score,
        "a": (a_ok, a_msg),
        "b": (b_ok, b_msg),
        "c": (c_ok, c_msg),
        "d": (d_ok, d_msg),
        "top_buyers": top3_buyers,
    }


# ============================================================
# Step 4: format output
# ============================================================

def format_full(s: dict, change_pct: float, close: float) -> str:
    icon = lambda ok: "✅" if ok else "❌"
    return (
        f"{s['code']} {s['name']} {change_pct:+.2f}% 收{close:.1f}\n"
        f"  A {icon(s['a'][0])} {s['a'][1]}\n"
        f"  B {icon(s['b'][0])} {s['b'][1]}\n"
        f"  C {icon(s['c'][0])} {s['c'][1]}\n"
        f"  D {icon(s['d'][0])} {s['d'][1]}\n"
        f"  買超: {s['top_buyers']}"
    )


def format_compact(s: dict, change_pct: float) -> str:
    flags = []
    flags.append("A" if s['a'][0] else "·")
    flags.append("B" if s['b'][0] else "·")
    flags.append("C" if s['c'][0] else "·")
    flags.append("D" if s['d'][0] else "·")
    return f"  [{ ''.join(flags) }] {s['code']} {s['name']} {change_pct:+.1f}%"


def format_report(target_date: str, scored: list[tuple[dict, dict]],
                  header: str = "", min_score: int = 0,
                  source_label: str = "今日漲停") -> str:
    """scored: list of (limitup_info, score_dict)"""
    title = header or f"🚀 ABCD 接力型訊號分析 {target_date}"
    lines = [title, ""]
    n_total = len(scored)
    n_strong = sum(1 for _, s in scored if s["score"] >= 3)
    lines.append(f"{source_label} {n_total} 檔 / 含明確訊號 (≥3/4): {n_strong} 檔")
    if min_score > 0:
        lines.append(f"(只列分數 ≥ {min_score}/4)")
    lines.append("")
    # Filter by min_score
    scored = [(i, s) for i, s in scored if s["score"] >= min_score]

    by_score = {4: [], 3: [], 2: [], 1: [], 0: []}
    for info, s in scored:
        by_score[s["score"]].append((info, s))

    if by_score[4]:
        lines.append("═══ ⭐⭐⭐⭐ 4/4 全訊號 ═══")
        for info, s in by_score[4]:
            lines.append(format_full(s, info["change_pct"], info["close"]))
            lines.append("")

    if by_score[3]:
        lines.append("═══ ⭐⭐⭐ 3/4 ═══")
        for info, s in by_score[3]:
            lines.append(format_full(s, info["change_pct"], info["close"]))
            lines.append("")

    if by_score[2]:
        lines.append("═══ ⭐⭐ 2/4 ═══")
        for info, s in by_score[2]:
            lines.append(format_compact(s, info["change_pct"]))
        lines.append("")

    if by_score[1] or by_score[0]:
        rest = by_score[1] + by_score[0]
        lines.append(f"═══ ≤1/4 (純拉抬，{len(rest)} 檔) ═══")
        codes = [f"{info['code']} {info['name']} +{info['change_pct']:.1f}%" for info, _ in rest]
        # 4 per line
        for i in range(0, len(codes), 4):
            lines.append("  " + " | ".join(codes[i:i+4]))

    return "\n".join(lines)


# ============================================================
# Telegram
# ============================================================

def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API_URL.format(token=bot_token)
    max_len = 4000
    chunks = []
    if len(message) <= max_len:
        chunks = [message]
    else:
        lines = message.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > max_len:
                chunks.append(chunk)
                chunk = line
            else:
                chunk = chunk + "\n" + line if chunk else line
        if chunk:
            chunks.append(chunk)

    all_ok = True
    for c in chunks:
        try:
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": c}).encode()
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except Exception as e:
            print(f"[ERROR] Telegram 送出失敗: {e}", file=sys.stderr)
            all_ok = False
    return all_ok


# ============================================================
# Main
# ============================================================

def main():
    p = argparse.ArgumentParser(description="ABCD 接力型訊號分析")
    p.add_argument("--date", help="目標日期 YYYY-MM-DD（預設今日）")
    p.add_argument("--min-pct", type=float, default=9.5, help="漲幅門檻 (預設 9.5%)")
    p.add_argument("--codes", help="逗號分隔代號清單；指定時跳過漲停掃描，直接對這些股票算 ABCD")
    p.add_argument("--codes-file", help="從 JSON 檔讀代號 (格式: [{code, name, ...}, ...])")
    p.add_argument("--min-score", type=int, default=0,
                   help="只列分數 ≥ N 的股票 (Layer 2 嚴格度，預設 0 = 全部分級顯示)")
    p.add_argument("--header", default="", help="自訂報告標題 (用於 wrapper)")
    p.add_argument("--token", default=os.environ.get("FINMIND_TOKEN", ""),
                   help="FinMind token (或 FINMIND_TOKEN 環境變數)")
    p.add_argument("--telegram", action="store_true", help="推送到 Telegram")
    p.add_argument("--bot-token", default=os.environ.get("TG_BOT_TOKEN", ""),
                   help="Telegram Bot Token (或 TG_BOT_TOKEN 環境變數)")
    p.add_argument("--chat-id", default=DEFAULT_CHAT_ID, help="Telegram Chat ID")
    p.add_argument("--quiet", action="store_true", help="不顯示掃描進度")
    p.add_argument("--limit", type=int, default=0, help="只掃前 N 檔 (0 = 全部，測試用)")
    args = p.parse_args()

    target = args.date or datetime.now().strftime("%Y-%m-%d")

    # Two modes: --codes/--codes-file (Layer 2 over given list) OR scan limit-up (standalone)
    if args.codes or args.codes_file:
        codes = []
        if args.codes_file:
            try:
                with open(args.codes_file) as f:
                    raw = json.load(f)
                for item in raw:
                    if isinstance(item, dict) and item.get("code"):
                        codes.append((item["code"], item.get("name", item["code"])))
                    elif isinstance(item, str):
                        codes.append((item, _get_zh_name(item, item)))
            except Exception as e:
                print(f"[ERROR] 讀取 {args.codes_file} 失敗: {e}", file=sys.stderr)
                sys.exit(1)
        if args.codes:
            for c in args.codes.split(","):
                c = c.strip()
                if c:
                    codes.append((c, _get_zh_name(c, c)))
        # Dedup
        seen = set()
        codes = [(c, n) for c, n in codes if not (c in seen or seen.add(c))]

        if not codes:
            print("[ERROR] --codes / --codes-file 未提供有效代號", file=sys.stderr)
            sys.exit(1)

        print(f"\n📅 分析日期: {target}", file=sys.stderr)
        print(f"📋 從輸入清單分析 {len(codes)} 檔", file=sys.stderr)
        # Build pseudo limitup info — we don't have the change_pct/close, fetch from price hist
        limitup = []
        for code, name in codes:
            px = fetch_price_history(code, target, args.token)
            close = px[-1]["close"] if px else 0
            prev = px[-2]["close"] if len(px) >= 2 else 0
            pct = (close - prev) / prev * 100 if prev > 0 else 0
            limitup.append({
                "code": code, "name": name, "close": close,
                "change_pct": pct, "volume": 0, "market": "",
            })
    else:
        print(f"\n📅 掃描日期: {target}", file=sys.stderr)
        print(f"📡 抓取全市場行情 ...", file=sys.stderr)
        quotes = fetch_market_quotes(target, args.token)
        if not quotes:
            print("[ERROR] 無資料 (非交易日或 API 失敗)", file=sys.stderr)
            sys.exit(1)

        limitup = find_limitup(quotes, args.min_pct)
        print(f"✅ 找到 {len(limitup)} 檔漲停 (≥{args.min_pct:.1f}%)", file=sys.stderr)

        if args.limit > 0:
            limitup = limitup[:args.limit]
            print(f"   (限制掃前 {args.limit} 檔)", file=sys.stderr)

        if not limitup:
            msg = f"📅 {target} 今日無漲停股 (≥{args.min_pct:.1f}%)"
            print(msg)
            if args.telegram and args.bot_token:
                send_telegram(msg, args.bot_token, args.chat_id)
            return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    scored = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {
            ex.submit(score_stock, info["code"], info["name"], target,
                      args.token, args.quiet): info
            for info in limitup
        }
        for fut in as_completed(futs):
            info = futs[fut]
            try:
                s = fut.result()
                scored.append((info, s))
            except Exception as e:
                print(f"  [ERR] {info['code']}: {e}", file=sys.stderr)

    # Sort: score desc, change_pct desc within tie
    scored.sort(key=lambda x: (-x[1]["score"], -x[0]["change_pct"]))

    source_label = "Layer 1 候選" if (args.codes or args.codes_file) else "今日漲停"
    report = format_report(target, scored, header=args.header,
                           min_score=args.min_score, source_label=source_label)
    print(report)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] 需要 Telegram Bot Token", file=sys.stderr)
            sys.exit(1)
        ok = send_telegram(report, args.bot_token, args.chat_id)
        print(f"\nTelegram: {'✅' if ok else '❌'}", file=sys.stderr)


if __name__ == "__main__":
    main()

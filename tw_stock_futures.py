#!/usr/bin/env python3
"""個股期(股票期貨)火熱排行 — 按成交量排名 + 熱門標記.

比照群益「個股期火熱排行」：全市場個股期按成交量排名，顯示 收盤/漲跌幅/
成交量/成交量增減/未平倉量/未平倉量增減 + 熱門標記(漲跌幅前十大/量排名躍升/
波動前二十/熱門)。

資料：FinMind TaiwanFuturesDaily(全市場個股期，成交量/未平倉/漲跌幅) +
TAIFEX 個股期標的對照(www.taifex.com.tw/cht/2/stockLists，2字母期貨前綴 →
標的股票代號+名稱)。

⚠ 純排行/觀察工具，非買賣訊號。
"""
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
MAPPING_CACHE = os.path.join(HERE, "concept_momentum", "cache",
                             "stock_futures_map.json")
TAIFEX_LIST = "https://www.taifex.com.tw/cht/2/stockLists"
UA = "Mozilla/5.0"

# 熱門標記門檻
HOT_TOP_N = 20            # 成交量前 N = 熱門
PCT_TOP_N = 10           # 漲跌幅(絕對值)前 N
VOL_TOP_N = 20           # 振幅前 N
RANK_JUMP_MIN = 30       # 成交量排名較前日上升 ≥ N 名 = 量躍升


def _http(url: str, timeout: int = 25) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"[WARN] {e}: {url[:80]}", file=sys.stderr)
        return None


def fetch_taifex_mapping(use_cache: bool = True) -> dict:
    """TAIFEX 個股期標的對照 → {2字母前綴: {stock, name, is_fut}}。
    對照近乎靜態 → 快取；抓失敗回快取或空。"""
    if use_cache and os.path.exists(MAPPING_CACHE):
        try:
            with open(MAPPING_CACHE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    h = _http(TAIFEX_LIST)
    if not h:
        return {}
    mp = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        c = [re.sub(r"<[^>]+>", "", x).strip()
             for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        c = [x for x in c if x]
        if (len(c) >= 4 and re.fullmatch(r"[A-Z]{2}", c[0])
                and re.fullmatch(r"\d{4,6}", c[2])):
            mp[c[0]] = {"stock": c[2], "name": c[3],
                        "is_fut": "股票期貨標的" in "".join(c)}
    if mp:
        os.makedirs(os.path.dirname(MAPPING_CACHE), exist_ok=True)
        tmp = MAPPING_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mp, f, ensure_ascii=False)
        os.replace(tmp, MAPPING_CACHE)
    return mp


def _agg_by_futures(rows: list[dict], date_iso: str) -> dict:
    """全市場 TaiwanFuturesDaily rows → {futures_id: {vol, oi, close,
    pct, high, low}}。跨契約月加總量/未平倉；價/漲跌幅取近月日盤。"""
    vol = defaultdict(float)
    oi = defaultdict(float)
    near: dict[str, dict] = {}       # 近月日盤代表列
    for r in rows:
        if r.get("date") != date_iso:
            continue
        fid = r.get("futures_id")
        if not fid:
            continue
        vol[fid] += r.get("volume", 0) or 0
        oi[fid] += r.get("open_interest", 0) or 0
        cd = str(r.get("contract_date", ""))
        # 近月 = contract_date 最小的月契約(6碼)；日盤優先
        if len(cd) == 6:
            cur = near.get(fid)
            better = (cur is None or cd < cur["_cd"]
                      or (cd == cur["_cd"]
                          and r.get("trading_session") == "position"))
            if better and r.get("close"):
                near[fid] = {"_cd": cd, "close": r["close"],
                             "pct": r.get("spread_per"),
                             "high": r.get("max"), "low": r.get("min")}
    out = {}
    for fid in vol:
        n = near.get(fid, {})
        out[fid] = {"vol": vol[fid], "oi": oi[fid],
                    "close": n.get("close"), "pct": n.get("pct"),
                    "high": n.get("high"), "low": n.get("low")}
    return out


def build_ranking(today_rows: list[dict], prev_rows: list[dict],
                  mapping: dict, today_iso: str, prev_iso: str,
                  top_n: int = HOT_TOP_N) -> list[dict]:
    """→ 個股期排行(依成交量降冪)，含增減與熱門標記。"""
    today = _agg_by_futures(today_rows, today_iso)
    prev = _agg_by_futures(prev_rows, prev_iso) if prev_rows else {}

    # 只留能對到標的股票的個股期(排除指數期/未對照)
    rows = []
    for fid, d in today.items():
        m = mapping.get(fid[:2])
        if not m or not m.get("is_fut"):
            continue
        p = prev.get(fid, {})
        rng = ((d["high"] - d["low"]) / d["close"] * 100
               if d.get("high") and d.get("low") and d.get("close") else None)
        rows.append({
            "fid": fid, "stock": m["stock"], "name": m["name"],
            "close": d["close"], "pct": d["pct"],
            "vol": int(d["vol"]), "oi": int(d["oi"]),
            "vol_chg": int(d["vol"] - (p.get("vol", 0) or 0)) if prev else None,
            "oi_chg": int(d["oi"] - (p.get("oi", 0) or 0)) if prev else None,
            "range_pct": round(rng, 2) if rng is not None else None,
        })

    # 依成交量排名(今日 + 前日，供量躍升)
    rows.sort(key=lambda r: -r["vol"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    prev_rank = {}
    if prev:
        pv = sorted(
            [(fid, d["vol"]) for fid, d in prev.items()
             if mapping.get(fid[:2], {}).get("is_fut")],
            key=lambda x: -x[1])
        prev_rank = {fid: i + 1 for i, (fid, _) in enumerate(pv)}

    # 熱門標記
    by_pct = sorted([r for r in rows if r["pct"] is not None],
                    key=lambda r: -abs(r["pct"]))[:PCT_TOP_N]
    pct_set = {r["fid"] for r in by_pct}
    by_rng = sorted([r for r in rows if r["range_pct"] is not None],
                    key=lambda r: -r["range_pct"])[:VOL_TOP_N]
    rng_set = {r["fid"] for r in by_rng}
    for r in rows:
        pr = prev_rank.get(r["fid"])
        r["rank_jump"] = (pr - r["rank"]) if pr else None
        r["f_pct_top"] = r["fid"] in pct_set              # 漲跌幅前十大
        r["f_range_top"] = r["fid"] in rng_set            # 波動前二十
        r["f_rank_jump"] = (r["rank_jump"] is not None
                            and r["rank_jump"] >= RANK_JUMP_MIN)  # 量躍升
        r["f_hot"] = r["rank"] <= HOT_TOP_N               # 熱門(量前N)
    return rows[:top_n] if top_n else rows


def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        import subprocess
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    except Exception:
        pass
    return ""


def _prev_trading_iso(today_iso: str) -> str:
    """前一交易日(用 taiex 交易日曆；退回前一日)。"""
    try:
        sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
        import market_breadth
        ds = market_breadth._twii_trading_dates(
            today_iso.replace("-", ""), 5)
        ds = [d for d in ds if d < today_iso.replace("-", "")]
        if ds:
            d = ds[-1]
            return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    except Exception:
        pass
    d = datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def fetch_ranking(date_iso: str | None = None, top_n: int = HOT_TOP_N
                  ) -> dict:
    """抓當日 + 前日全市場個股期 → 排行。回 {date, rows} 或 {error}。"""
    token = _token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    sys.path.insert(0, HERE)
    import finmind_client as fc
    today_iso = date_iso or datetime.now().strftime("%Y-%m-%d")
    prev_iso = _prev_trading_iso(today_iso)
    mapping = fetch_taifex_mapping()
    if not mapping:
        return {"error": "TAIFEX 對照抓取失敗"}
    # FinMind 全市場範圍查詢只回第一天(quirk)→ 兩次單日查
    try:
        today_rows = fc._call("TaiwanFuturesDaily",
                              {"start_date": today_iso,
                               "end_date": today_iso}, token)
        prev_rows = fc._call("TaiwanFuturesDaily",
                             {"start_date": prev_iso,
                              "end_date": prev_iso}, token)
    except Exception as e:
        return {"error": f"FinMind: {type(e).__name__}: {e}"}
    today_rows = [r for r in today_rows if r.get("date") == today_iso]
    prev_rows = [r for r in prev_rows if r.get("date") == prev_iso]
    if not today_rows:
        return {"error": f"{today_iso} 無個股期資料"}
    ranking = build_ranking(today_rows, prev_rows, mapping,
                            today_iso, prev_iso, top_n=top_n)
    return {"date": today_iso, "prev": prev_iso, "rows": ranking}


def format_report(data: dict) -> str:
    """Telegram/LINE 純文字排行報告(成交量 Top N + 熱門標記)。"""
    if data.get("error"):
        return f"個股期火熱排行: {data['error']}"
    d = data["date"]
    lines = [f"🔥 個股期火熱排行 ({d[:4]}/{d[5:7]}/{d[8:]})",
             f"依個股期成交量排名 Top {len(data['rows'])}｜⚠ 觀察工具、非買賣訊號",
             "（成交量=今日期貨成交口數；未平倉=留倉口數；括號為較前一交易日增減）",
             "━━━━━━━━━━━━"]
    for r in data["rows"]:
        arrow = "▲" if (r["pct"] or 0) > 0 else "▼"
        flags = " ".join(filter(None, [
            "🔟漲跌前十" if r["f_pct_top"] else "",
            f"🚀量躍升{r['rank_jump']}名" if r["f_rank_jump"] else "",
            "〰振幅前廿" if r["f_range_top"] else "",
        ]))
        vc = (f"（{'+' if r['vol_chg'] >= 0 else ''}{r['vol_chg']:,}）"
              if r["vol_chg"] is not None else "")
        oc = (f"（{'+' if r['oi_chg'] >= 0 else ''}{r['oi_chg']:,}）"
              if r["oi_chg"] is not None else "")
        # 第一行：排名/標的/期貨代碼/收盤/漲跌幅
        lines.append(
            f"{r['rank']:>2}. {r['stock']} {r['name']}（{r['fid']}）"
            f" 收{r['close']:g} {arrow}{r['pct']:+.2f}%")
        # 第二行：成交量 + 未平倉 + 標記
        lines.append(
            f"     成交量 {r['vol']:,} 口{vc}｜未平倉 {r['oi']:,} 口{oc}"
            + (f"  {flags}" if flags else ""))
    lines.append("━━━━━━━━━━━━")
    lines.append("標記說明：🔟=當日漲跌幅絕對值前十大　"
                 "🚀=成交量排名較前一交易日大幅上升(≥30名)　"
                 "〰=當日振幅(高−低)/收盤 前二十大")
    return "\n".join(lines)


def render_html(data: dict) -> str:
    """網頁排行表(比照群益個股期火熱排行)。"""
    import html as _h
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/chip-price">📋 籌碼價量</a> '
           '<a href="/money-flow">💰 族群資金流</a> '
           '<a href="/warrant-signal">🎰 權證量能</a> '
           '<a href="/stock-futures">🔥 個股期火熱</a> <a href="/lin-matrix">📐 林則行矩陣</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1080px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.85em;}
  th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;}
  th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left;}
  th{background:#fafafa;color:#555;}
  .up{color:#c0392b;} .dn{color:#186a3b;}
  .pos{color:#c0392b;} .neg{color:#186a3b;}
  .small,small{font-size:.85em;color:#666;}
  .flag{font-size:.9em;}
</style>"""
    d = data.get("date", "")
    fmt = f"{d[:4]}/{d[5:7]}/{d[8:]}" if len(d) == 10 else d
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>個股期火熱排行</title>{css}</head><body>{nav}'
            f'<h1>🔥 個股期火熱排行 — {fmt}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'
    rows_html = []
    for r in data["rows"]:
        pcls = "up" if (r["pct"] or 0) > 0 else "dn"
        arrow = "▲" if (r["pct"] or 0) > 0 else "▼"
        def _chg(v):
            if v is None:
                return "—"
            cls = "pos" if v >= 0 else "neg"
            return f'<span class="{cls}">{v:+,}</span>'
        flags = " ".join(filter(None, [
            "🔟" if r["f_pct_top"] else "",
            f"🚀{r['rank_jump']}" if r["f_rank_jump"] else "",
            "〰" if r["f_range_top"] else "",
            "熱" if r["f_hot"] else "",
        ]))
        rows_html.append(
            f'<tr><td>{r["rank"]}</td>'
            f'<td>{_h.escape(r["stock"])} {_h.escape(r["name"])}</td>'
            f'<td>{_h.escape(r["fid"])}</td>'
            f'<td>{r["close"]:g}</td>'
            f'<td class="{pcls}">{arrow}{r["pct"]:+.2f}%</td>'
            f'<td>{r["vol"]:,}</td><td>{_chg(r["vol_chg"])}</td>'
            f'<td>{r["oi"]:,}</td><td>{_chg(r["oi_chg"])}</td>'
            f'<td class="flag">{flags}</td></tr>')
    return (head +
            '<section><p class="small">全市場個股期依<b>成交量</b>排名。'
            '標記：🔟漲跌幅(絕對值)前十、🚀量排名躍升(較前日≥30名)、'
            '〰日振幅(高-低/收)前二十、熱=成交量前二十。'
            '⚠ 純排行/觀察工具、非買賣訊號。</p>'
            '<div style="overflow-x:auto"><table><thead><tr>'
            '<th>#</th><th>標的</th><th>期代</th><th>收盤</th><th>漲跌幅</th>'
            '<th>成交量</th><th>量增減</th><th>未平倉</th><th>倉增減</th>'
            '<th>標記</th></tr></thead><tbody>'
            + "".join(rows_html) +
            f'</tbody></table></div><p class="small">資料至 {fmt}（前一交易日 '
            f'{_h.escape(data.get("prev",""))} 比較）</p></section></body></html>')


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--top", type=int, default=HOT_TOP_N)
    ap.add_argument("--json-out")
    ap.add_argument("--line-to", help="LINE 收件者(逗號分隔)")
    args = ap.parse_args()
    data = fetch_ranking(args.date, top_n=args.top)
    print(format_report(data))
    if args.json_out and not data.get("error"):
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    if args.line_to and not data.get("error"):
        import line_push
        tok = line_push.resolve_token()
        if tok:
            for r in [x.strip() for x in args.line_to.split(",") if x.strip()]:
                ok = line_push.push_text(format_report(data), tok, r)
                print(f"LINE → {r[:6]}…: {'✅' if ok else '❌'}",
                      file=sys.stderr)


if __name__ == "__main__":
    main()

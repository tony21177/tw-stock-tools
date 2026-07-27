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
    oi_by_cd: dict[str, dict] = defaultdict(dict)   # fid → {6碼契約月: OI}
    close_by_cd: dict[str, dict] = defaultdict(dict)  # fid → {6碼契約月: 日盤收}
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
            # 單月契約的未平倉(日盤才有 OI;夜盤/價差為 0)→ 記錄以拆近月/遠月
            oiv = r.get("open_interest", 0) or 0
            if oiv:
                oi_by_cd[fid][cd] = oiv
            if r.get("trading_session") == "position" and r.get("close"):
                close_by_cd[fid][cd] = r["close"]      # 各月日盤收(算月價差)
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
        cds = oi_by_cd.get(fid, {})
        near_cd = min(cds) if cds else None          # 最小契約月 = 近月
        near_oi = cds.get(near_cd, 0) if near_cd else 0
        far_oi = sum(v for c, v in cds.items() if c != near_cd)
        # 近遠月價差 = 次近月日盤收 − 近月日盤收(期限結構)
        ccl = close_by_cd.get(fid, {})
        months = sorted(ccl)
        month_spread = (round(ccl[months[1]] - ccl[months[0]], 2)
                        if len(months) >= 2 else None)
        out[fid] = {"vol": vol[fid], "oi": oi[fid],
                    "near_oi": near_oi, "far_oi": far_oi,
                    "near_cd": n.get("_cd"), "month_spread": month_spread,
                    "close": n.get("close"), "pct": n.get("pct"),
                    "high": n.get("high"), "low": n.get("low")}
    return out


def _days_to_settle(near_cd: str | None, today_iso: str) -> int | None:
    """距近月結算日(該月第三個週三)的日曆天數。"""
    if not near_cd or len(near_cd) != 6:
        return None
    try:
        y, m = int(near_cd[:4]), int(near_cd[4:6])
        first = datetime(y, m, 1)
        # 第一個週三 + 14 天 = 第三個週三(週三 weekday()==2)
        third_wed = first + timedelta(days=(2 - first.weekday()) % 7 + 14)
        today = datetime.strptime(today_iso, "%Y-%m-%d")
        return (third_wed - today).days
    except Exception:
        return None


# 量價未平倉四象限:依「當日漲跌 × 總未平倉增減」判部位性質
_QUAD = {
    (True, True): ("🟥新多進場", "價漲+增倉:多方新單進場,漲勢有部位支撐"),
    (True, False): ("🟧空單回補", "價漲+減倉:空單回補/軋空推升,續航力較弱"),
    (False, True): ("🟩新空進場", "價跌+增倉:空方新單進場,空方力道強"),
    (False, False): ("🟦多單了結", "價跌+減倉:多單停損/獲利了結,跌勢或近尾聲"),
}


def _quadrant(pct, oi_chg) -> dict | None:
    """量價未平倉四象限。回 {label, desc} 或 None(缺資料)。"""
    if pct is None or oi_chg is None or pct == 0 or oi_chg == 0:
        return None
    label, desc = _QUAD[(pct > 0, oi_chg > 0)]
    return {"label": label, "desc": desc}


def build_ranking(today_rows: list[dict], prev_rows: list[dict],
                  mapping: dict, today_iso: str, prev_iso: str,
                  top_n: int = HOT_TOP_N, cash_close: dict | None = None,
                  inst: dict | None = None) -> list[dict]:
    """→ 個股期排行(依成交量降冪)，含增減與熱門標記。
    cash_close = {股票代號: 現貨收盤}(算基差);inst = {fid: 法人淨口數}。"""
    today = _agg_by_futures(today_rows, today_iso)
    prev = _agg_by_futures(prev_rows, prev_iso) if prev_rows else {}
    cash_close = cash_close or {}
    inst = inst or {}

    # 只留能對到標的股票的個股期(排除指數期/未對照)
    rows = []
    for fid, d in today.items():
        m = mapping.get(fid[:2])
        if not m or not m.get("is_fut"):
            continue
        p = prev.get(fid, {})
        rng = ((d["high"] - d["low"]) / d["close"] * 100
               if d.get("high") and d.get("low") and d.get("close") else None)
        oi_chg = int(d["oi"] - (p.get("oi", 0) or 0)) if prev else None
        near_chg = int(d["near_oi"] - (p.get("near_oi", 0) or 0)) if prev else None
        far_chg = int(d["far_oi"] - (p.get("far_oi", 0) or 0)) if prev else None
        # 基差 = 近月期貨收 − 現貨收(點與%);週轉 = 量/未平倉
        cc = cash_close.get(m["stock"])
        basis = (round(d["close"] - cc, 2)
                 if d.get("close") and cc else None)
        basis_pct = (round((d["close"] - cc) / cc * 100, 2)
                     if d.get("close") and cc else None)
        turnover = (round(d["vol"] / d["oi"], 2)
                    if d.get("oi") else None)
        rows.append({
            "fid": fid, "stock": m["stock"], "name": m["name"],
            "close": d["close"], "pct": d["pct"],
            "vol": int(d["vol"]), "oi": int(d["oi"]),
            "near_oi": int(d["near_oi"]), "far_oi": int(d["far_oi"]),
            "vol_chg": int(d["vol"] - (p.get("vol", 0) or 0)) if prev else None,
            "oi_chg": oi_chg, "near_oi_chg": near_chg, "far_oi_chg": far_chg,
            "quadrant": _quadrant(d["pct"], oi_chg),
            "basis": basis, "basis_pct": basis_pct, "turnover": turnover,
            "month_spread": d.get("month_spread"),
            "days_settle": _days_to_settle(d.get("near_cd"), today_iso),
            "inst_net": inst.get(fid),
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
    # 現貨收盤(算基差)+ 法人個股期淨部位(僅部分商品有)
    cash_close = _fetch_cash_close(fc, today_iso, token)
    inst = _fetch_inst_net(fc, today_iso, token)
    ranking = build_ranking(today_rows, prev_rows, mapping,
                            today_iso, prev_iso, top_n=top_n,
                            cash_close=cash_close, inst=inst)
    return {"date": today_iso, "prev": prev_iso, "rows": ranking,
            "inst_n": len(inst)}


def _fetch_cash_close(fc, date_iso: str, token: str) -> dict:
    """全市場現貨收盤 {股票代號: close}(FinMind TaiwanStockPrice 單日全市場)。"""
    try:
        rows = fc._call("TaiwanStockPrice",
                        {"start_date": date_iso, "end_date": date_iso}, token)
        return {r["stock_id"]: r["close"] for r in rows
                if r.get("date") == date_iso and r.get("close")}
    except Exception:
        return {}


def _fetch_inst_net(fc, date_iso: str, token: str) -> dict:
    """三大法人個股期淨留倉 {fid: 淨口數(多−空)}。FinMind 僅涵蓋部分商品。"""
    try:
        rows = fc._call("TaiwanFuturesInstitutionalInvestors",
                        {"start_date": date_iso, "end_date": date_iso}, token)
    except Exception:
        return {}
    net = defaultdict(int)
    for r in rows:
        if r.get("date") != date_iso:
            continue
        fid = r.get("futures_id")
        if not fid:
            continue
        net[fid] += ((r.get("long_open_interest_balance_volume", 0) or 0)
                     - (r.get("short_open_interest_balance_volume", 0) or 0))
    return dict(net)


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
  th{background:#fafafa;color:#555;cursor:pointer;user-select:none;white-space:nowrap;}
  th:hover{background:#eef2f7;} th .ar{color:#0066cc;font-size:.9em;}
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
                return '<td data-v="NaN">—</td>'
            cls = "pos" if v >= 0 else "neg"
            return f'<td data-v="{v}"><span class="{cls}">{v:+,}</span></td>'
        flags = " ".join(filter(None, [
            "🔟" if r["f_pct_top"] else "",
            f"🚀{r['rank_jump']}" if r["f_rank_jump"] else "",
            "〰" if r["f_range_top"] else "",
            "熱" if r["f_hot"] else "",
        ]))
        # 標記排序權重(越熱越大)
        fscore = ((4 if r["f_hot"] else 0) + (2 if r["f_pct_top"] else 0)
                  + (1 if r["f_rank_jump"] else 0) + (1 if r["f_range_top"] else 0))
        q = r.get("quadrant")
        if q:
            qscore = {"🟥新多進場": 2, "🟧空單回補": 1,
                      "🟦多單了結": -1, "🟩新空進場": -2}[q["label"]]
            qcell = (f'<td data-v="{qscore}" title="{_h.escape(q["desc"])}">'
                     f'{q["label"]}</td>')
        else:
            qcell = '<td data-v="NaN">—</td>'
        # 基差(近月期貨−現貨):升水(+)紅、貼水(−)綠
        b, bp = r.get("basis"), r.get("basis_pct")
        if b is not None:
            bcell = (f'<td data-v="{bp}" class="{"pos" if b >= 0 else "neg"}" '
                     f'title="升水(+)看多／貼水(−)看跌;除息旺季貼水為結構性">'
                     f'{b:+g}({bp:+.2f}%)</td>')
        else:
            bcell = '<td data-v="NaN">—</td>'
        tv = r.get("turnover")
        tcell = (f'<td data-v="{tv}" title="量/未平倉;高=當沖churn、低=佈局留倉">'
                 f'{tv:g}x</td>') if tv is not None else '<td data-v="NaN">—</td>'
        ms = r.get("month_spread")
        mscell = (f'<td data-v="{ms}">{ms:+g}</td>'
                  if ms is not None else '<td data-v="NaN">—</td>')
        inet = r.get("inst_net")
        if inet is not None:
            icell = (f'<td data-v="{inet}"><span class="{"pos" if inet >= 0 else "neg"}">'
                     f'{inet:+,}</span></td>')
        else:
            icell = '<td data-v="NaN">—</td>'
        ds = r.get("days_settle")
        dscell = (f'<td data-v="{ds}">{ds}天</td>'
                  if ds is not None else '<td data-v="NaN">—</td>')
        rows_html.append(
            f'<tr><td data-v="{r["rank"]}">{r["rank"]}</td>'
            f'<td>{_h.escape(r["stock"])} {_h.escape(r["name"])}</td>'
            f'<td>{_h.escape(r["fid"])}</td>'
            f'<td data-v="{r["close"]}">{r["close"]:g}</td>'
            f'<td data-v="{r["pct"]}" class="{pcls}">{arrow}{r["pct"]:+.2f}%</td>'
            f'{bcell}'
            f'<td data-v="{r["vol"]}">{r["vol"]:,}</td>{_chg(r["vol_chg"])}'
            f'<td data-v="{r["oi"]}">{r["oi"]:,}</td>{tcell}'
            f'{_chg(r.get("near_oi_chg"))}{_chg(r.get("far_oi_chg"))}'
            f'{mscell}{icell}{qcell}{dscell}'
            f'<td data-v="{fscore}" class="flag">{flags}</td></tr>')
    inst_n = data.get("inst_n", 0)
    return (head +
            '<section><p class="small">全市場個股期依<b>成交量</b>排名。'
            '<b>點欄位標題可排序</b>(再點一次反向;各欄意義見下方說明)。'
            f'⚠ 法人淨僅 {inst_n} 檔商品有資料(FinMind 未全覆蓋),其餘顯示「—」。'
            '純排行/觀察工具、非買賣訊號。</p>'
            '<div style="overflow-x:auto"><table id="ftable"><thead><tr>'
            + "".join(f'<th onclick="sortT({i})">{lbl}<span class="ar"></span></th>'
                      for i, lbl in enumerate(
                          ["#", "標的", "期代", "收盤", "漲跌幅", "基差",
                           "成交量", "量增減", "未平倉", "週轉", "近月倉增減",
                           "遠月倉增減", "近遠價差", "法人淨", "象限",
                           "距結算", "標記"])) +
            '</tr></thead><tbody>'
            + "".join(rows_html) +
            f'</tbody></table></div><p class="small">資料至 {fmt}（前一交易日 '
            f'{_h.escape(data.get("prev",""))} 比較）</p></section>'
            + _QUAD_LEGEND + _COL_GLOSSARY + _SORT_JS + '</body></html>')


_QUAD_LEGEND = """<section>
<h3 style="font-size:1.05em;margin:.3em 0">📐 量價未平倉四象限(象限欄)</h3>
<p class="small">依「當日<b>漲跌</b> × 總<b>未平倉增減</b>」判斷部位性質。未平倉增減只代表
部位增/減、<b>不直接分多空</b>,需搭配漲跌一起看:</p>
<table style="max-width:640px"><thead><tr><th></th><th>倉增(新單進場)</th><th>倉減(平倉退場)</th></tr></thead>
<tbody>
<tr><td style="text-align:left">價漲</td><td>🟥<b>新多進場</b><br><span class="small">多方新單,漲勢有部位支撐(較健康)</span></td>
<td>🟧<b>空單回補</b><br><span class="small">軋空/空單回補推升,續航力較弱</span></td></tr>
<tr><td style="text-align:left">價跌</td><td>🟩<b>新空進場</b><br><span class="small">空方新單,空方力道強</span></td>
<td>🟦<b>多單了結</b><br><span class="small">多單停損/獲利了結,跌勢或近尾聲</span></td></tr>
</tbody></table></section>"""

_COL_GLOSSARY = """<section>
<h3 style="font-size:1.05em;margin:.3em 0">📖 各欄計算方式</h3>
<ul class="small" style="line-height:1.7;margin:.2em 0 0 1em;padding:0">
<li><b>#</b> — 依成交量由大到小的排名。</li>
<li><b>標的 / 期代</b> — 個股期對應的股票代號+名稱 / 期貨商品代碼(2字前綴,TAIFEX 對照表)。</li>
<li><b>收盤 / 漲跌幅</b> — <b>近月</b>契約(最小到期月)的收盤與較前一結算漲跌幅(FinMind spread_per)。</li>
<li><b>基差</b> — <b>近月期貨收盤 − 現貨收盤</b>(點數,括號為佔現貨%)。<b>升水(+)偏多、貼水(−)偏空</b>;⚠ 除權息旺季貼水多為結構性(待除息)、非看空。現貨收盤取自 FinMind TaiwanStockPrice。</li>
<li><b>成交量</b> — 該個股期<b>所有到期月契約加總</b>的當日成交口數。</li>
<li><b>量增減</b> — 今日成交量 − 前一交易日成交量。</li>
<li><b>未平倉</b> — 所有月份契約<b>加總</b>的當日未平倉口數(收盤仍留倉、未沖銷的部位;夜盤/價差單為 0 不重複計)。</li>
<li><b>週轉</b> — <b>成交量 ÷ 未平倉</b>。<b>高=當沖投機churn(隔日沖)、低=佈局留倉</b>;分辨「投機爆量」與「主力建倉」。</li>
<li><b>近月倉增減</b> — <b>近月</b>契約未平倉 今日 − 前一交易日。近月最活躍,是當日建/減倉主戰場;⚠ 結算換月時近月部位會移往次月,近月會急縮。</li>
<li><b>遠月倉增減</b> — <b>近月以外</b>所有月份未平倉加總 今日 − 前一交易日。換月時遠月會相對增加。</li>
<li><b>近遠價差</b> — <b>次近月日盤收 − 近月日盤收</b>(點數)。期限結構:反映除息預期與換月佈局;配近/遠月倉增減看。</li>
<li><b>法人淨</b> — <b>三大法人(外資+投信+自營)在該個股期的淨留倉口數(多方留倉 − 空方留倉)</b>,+ = 淨多、− = 淨空。這是「未平倉不分多空」最直接的解答。⚠ 資料源 FinMind TaiwanFuturesInstitutionalInvestors <b>僅涵蓋部分商品</b>(台積 CDF 等未含),無資料顯示「—」。</li>
<li><b>象限</b> — 見上方四象限(用漲跌 × 總未平倉增減)。</li>
<li><b>距結算</b> — 距近月結算日(該月第三個週三)的日曆天數;臨近(個位數)代表換月/波動放大。</li>
<li><b>標記</b> — 🔟漲跌幅絕對值前十、🚀量排名較前日躍升≥30名、〰日振幅(高−低)/收前二十、熱=成交量前二十。</li>
</ul></section>"""


_SORT_JS = """<script>
function sortT(col){
  var t=document.getElementById('ftable'), tb=t.tBodies[0];
  var rows=Array.prototype.slice.call(tb.rows);
  var dir=(t.dataset.col==col && t.dataset.dir=='asc')?'desc':'asc';
  rows.sort(function(a,b){
    var x=a.cells[col], y=b.cells[col];
    var xv=x.getAttribute('data-v'), yv=y.getAttribute('data-v'), r;
    if(xv!==null && yv!==null){
      var xn=parseFloat(xv), yn=parseFloat(yv);
      if(isNaN(xn)&&isNaN(yn)) return 0;
      if(isNaN(xn)) return 1;            // 缺值永遠沉底
      if(isNaN(yn)) return -1;
      r=xn-yn;
    } else { r=x.textContent.trim().localeCompare(y.textContent.trim(),'zh-Hant'); }
    return dir=='asc'?r:-r;
  });
  rows.forEach(function(row){tb.appendChild(row);});
  t.dataset.col=col; t.dataset.dir=dir;
  var ths=t.tHead.rows[0].cells;
  for(var i=0;i<ths.length;i++){var a=ths[i].querySelector('.ar'); if(a)a.textContent='';}
  var ar=ths[col].querySelector('.ar'); if(ar)ar.textContent=(dir=='asc'?' ▲':' ▼');
}
</script>"""


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

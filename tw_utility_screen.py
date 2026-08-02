#!/usr/bin/env python3
"""
Utility Screen 抗跌領頭羊 (tw_utility_screen) — Minervini 修正期區間 RS 篩選

概念(Minervini;用戶提供文章 2026-08-02):大盤修正期間,絕大多數股票跟跌;
下一波的超級強勢股通常在修正期就展現異常抗跌(高相對強度、貼近高點、
量縮不跌)。Utility Screen 就是在市場最亂時定位這些未來領頭羊。

啟動條件:加權指數距「200 日內最高收盤」超過 20 個交易日 → 啟動,
  以「距高點天數 N」為視窗重算區間 RS(N 逐日 +1);
  大盤創高或 N>200 → 退回標準年 RS(N=250)。
區間 RS(IBD 加權式,視窗切四段、最近一段雙倍權重):
  score = 2×r(最近N/4) + r(次N/4) + r(再次N/4) + r(最舊N/4)
  → 全市場百分位排名 1~99。
濾網(文章口徑,排除一年低點相關):
  區間RS > 85、股價 > MA200、MA50 > MA200、日均成交額 > 1億(近20日,
  vol×收盤 估算)、距自身 200 日高 < 25%。

資料:year_prices 還原價快取(收盤/高低)+ vol_day 量快取 + TAIEX(FinMind)。
⚠ 未回測、觀察清單非買賣訊號;搭配 FTD(/ftd)找大盤轉折進場時機。

用法:
  tw_utility_screen.py --build     # 掃描 + 寫 cache/utility_screen_latest.json
  tw_utility_screen.py --html      # debug 網頁
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
import tw_extremes as ex                     # noqa: E402
import tw_margin_scan as ms                  # noqa: E402(重用 _vol_day)

CACHE = os.path.join(HERE, "concept_momentum", "cache")
LATEST = os.path.join(CACHE, "utility_screen_latest.json")

ACT_MIN = 20        # 距高點 > 此交易日數才啟動 utility mode
ACT_MAX = 200       # 超過則退回標準年 RS
RS_MIN = 85         # 區間 RS 百分位門檻
DIST_MAX = 0.25     # 距自身 200 日高 < 25%
MONEY_MIN = 1e8     # 日均成交額 > 1 億(近 20 日,vol×收盤 估)
STD_N = 250         # 非啟動期:標準年 RS 視窗


def _fut_star(code):
    try:
        import tw_stock_futures as _sf
        return " ★" if code in _sf.fut_stock_set() else ""
    except Exception:
        return ""


def market_state(token: str) -> dict:
    """加權指數:距 200 日內最高收盤幾個交易日。"""
    rows = ex._fm("TaiwanStockPrice",
                  {"data_id": "TAIEX", "start_date": "2025-01-01"}, token)
    seq = [(r["date"], r["close"]) for r in rows if r.get("close")]
    c = [x[1] for x in seq]
    win = c[-ACT_MAX:]
    peak = max(win)
    idx_in_win = len(win) - 1 - win[::-1].index(peak)
    idx = len(c) - len(win) + idx_in_win
    days = len(c) - 1 - idx
    return {"date": seq[-1][0], "close": c[-1],
            "peak": peak, "peak_date": seq[idx][0],
            "days_since": days,
            "drawdown": round((c[-1] / peak - 1) * 100, 1),
            "active": ACT_MIN < days <= ACT_MAX}


def _rs_score(closes: list[float], n: int) -> float | None:
    """IBD 加權區間 RS 原始分:視窗 n 切四段,最近段雙倍權重。"""
    if len(closes) < n + 1:
        return None
    q = max(1, n // 4)
    try:
        c0 = closes[-1]
        r1 = c0 / closes[-1 - q] - 1
        r2 = closes[-1 - q] / closes[-1 - 2 * q] - 1
        r3 = closes[-1 - 2 * q] / closes[-1 - 3 * q] - 1
        r4 = closes[-1 - 3 * q] / closes[-1 - n] - 1
    except (IndexError, ZeroDivisionError):
        return None
    return 2 * r1 + r2 + r3 + r4


def scan(token: str | None = None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    st = market_state(token)
    n = st["days_since"] if st["active"] else STD_N
    dates = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    names = ex._finmind_names(token)

    # 價格序列(還原)
    closes: dict = {}
    highs: dict = {}
    dks = []
    for d in dates:
        dp = ex._day_prices(d, token)
        if not dp:
            continue
        dks.append(d)
        for c, v in dp.items():
            if not (len(c) == 4 and c.isdigit() and not c.startswith("00")):
                continue
            closes.setdefault(c, []).append(v[2])
            highs.setdefault(c, []).append(v[0])
    # 近 20 日量(張)→ 日均成交額估算
    vol20: dict = {}
    for d in dates[-20:]:
        vd = ms._vol_day(d, token)
        dp = ex._day_prices(d, token)
        for c, v in vd.items():
            if c in closes and dp.get(c):
                vol20.setdefault(c, []).append(v * dp[c][2] * 1000)

    # 全市場區間 RS 原始分 → 百分位
    scores = {}
    for c, cs in closes.items():
        s = _rs_score(cs, n)
        if s is not None:
            scores[c] = s
    ranked = sorted(scores, key=lambda x: scores[x])
    pct = {c: round((i + 1) / len(ranked) * 99, 1)
           for i, c in enumerate(ranked)}

    rows = []
    for c, rs in pct.items():
        if rs <= RS_MIN:
            continue
        cs = closes[c]
        if len(cs) < 200:
            continue
        cur = cs[-1]
        ma50 = sum(cs[-50:]) / 50
        ma200 = sum(cs[-200:]) / 200
        if cur <= ma200 or ma50 <= ma200:
            continue
        hi200 = max(highs[c][-200:])
        dist = 1 - cur / hi200
        if dist >= DIST_MAX:
            continue
        money = sum(vol20.get(c, [])) / max(len(vol20.get(c, [])), 1)
        if money < MONEY_MIN:
            continue
        win_ret = (cur / cs[-1 - n] - 1) * 100 if len(cs) > n else None
        rows.append({
            "code": c, "name": names.get(c, "") + _fut_star(c),
            "close": round(cur, 2), "rs": rs,
            "win_ret": round(win_ret, 1) if win_ret is not None else None,
            "dist_high": round(dist * 100, 1),
            "ma50_gt": True,
            "money_e8": round(money / 1e8, 2),
        })
    rows.sort(key=lambda r: -r["rs"])
    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": dks[-1] if dks else "",
        "market": st, "n_window": n,
        "mode": "utility" if st["active"] else "standard",
        "n_universe": len(scores),
        "rows": rows,
    }


def build_and_save(token: str | None = None) -> dict:
    data = scan(token)
    if not data.get("error"):
        tmp = LATEST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, LATEST)
    return data


def render_html(data: dict) -> str:
    import html as _h
    nav = __import__("site_nav").nav_html("/utility-screen")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06);overflow-x:auto;}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;}
  th:nth-child(2),td:nth-child(2){text-align:left;} th{background:#eef2f7;}
  .up{color:#c0392b;} .dn{color:#0a8a3a;}
  .rs{color:#fff;background:#1f6feb;border-radius:3px;padding:1px 6px;}
  .small{font-size:.85em;color:#666;}
  .note{background:#fff9ec;border:1px solid #f0dca8;border-radius:6px;
        padding:10px 14px;font-size:.86em;line-height:1.65;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Utility Screen 抗跌領頭羊</title>{css}</head><body>{nav}'
            f'<h1>🛡 Utility Screen 抗跌領頭羊(Minervini)</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'
    st = data["market"]
    n = data["n_window"]
    if data["mode"] == "utility":
        banner = (f'<section class="sigs" style="background:#2b230c;border:1px solid #5c4c1d;'
                  f'border-radius:6px;padding:10px 14px;color:#e6c56a">'
                  f'⚡ <b>Utility mode 啟動中</b> — 加權距 200 日高 '
                  f'{st["peak"]:,.0f}({st["peak_date"]})已 <b>{st["days_since"]} 個交易日</b>、'
                  f'修正 {st["drawdown"]}% → 區間 RS 視窗 = <b>{n} 天</b>(明日自動 +1,'
                  f'直到大盤創高或 >200 天)。</section>')
    else:
        banner = (f'<section style="background:#151b23;border:1px solid #223041;'
                  f'border-radius:6px;padding:10px 14px" class="small">'
                  f'大盤距 200 日高 {st["days_since"]} 個交易日(啟動需 >{ACT_MIN});'
                  f'目前顯示<b>標準年 RS(250 天)</b>版篩選。</section>')
    rows = data["rows"]
    body = [banner,
            f'<section><p class="small">濾網:區間RS>{RS_MIN}(全市場百分位,'
            f'IBD 加權式=視窗切四段、最近段雙倍)+ 股價>MA200 + MA50>MA200 + '
            f'日均成交額>1億(近20日估)+ 距自身200日高<{DIST_MAX:.0%}。'
            f'母體 {data["n_universe"]} 檔 → 符合 <b>{len(rows)}</b> 檔,依 RS 排序。'
            f'點代號看 K 線。</p></section>']
    if rows:
        h = ['<section><table><thead><tr><th>#</th><th>標的</th><th>現價</th>'
             f'<th>區間RS</th><th>{n}日報酬</th><th>距200日高</th>'
             '<th>日均額(億)</th></tr></thead><tbody>']
        for i, r in enumerate(rows, 1):
            wr = r["win_ret"]
            h.append(
                f'<tr><td data-v="{i}">{i}</td>'
                f'<td data-v="{r["code"]}">{_h.escape(r["code"])} {_h.escape(r["name"])}</td>'
                f'<td data-v="{r["close"]}">{r["close"]:g}</td>'
                f'<td data-v="{r["rs"]}"><span class="rs">{r["rs"]:.0f}</span></td>'
                f'<td data-v="{wr}" class="{"up" if (wr or 0) > 0 else "dn"}">'
                f'{wr:+.1f}%</td>'
                f'<td data-v="{r["dist_high"]}">−{r["dist_high"]:.1f}%</td>'
                f'<td data-v="{r["money_e8"]}">{r["money_e8"]:.1f}</td></tr>')
        h.append('</tbody></table></section>')
        body.append("".join(h))
    else:
        body.append('<section><p class="small">(目前無符合標的)</p></section>')

    glossary = f"""<section class="note">📖 <b>這在找什麼(白話)</b><br>
• <b>概念(Minervini Utility Screen)</b>:大盤修正時多數股票跟跌,但<b>下一波牛市的
領頭羊通常在修正期就異常抗跌</b> —— 大盤跌 10~20% 它只回 5~10%、貼著高點整理、
量縮不破底。這個篩選就是在市場最亂時把它們找出來放進觀察清單。<br>
• <b>區間 RS</b>:啟動後不用固定一年,改用「大盤距高點的天數」當視窗
(今天 {n} 天、明天 {n + 1} 天…)重算相對強度 —— 專門衡量「<b>這波修正裡</b>誰最強」。
公式與年 RS 同款(IBD 加權:視窗切四段、最近段雙倍權重),再取全市場百分位(1~99)。<br>
• <b>濾網意義</b>:RS>{RS_MIN}=贏過 {RS_MIN}% 的股票;股價>MA200 且 MA50>MA200=長多結構未壞;
距自身 200 日高<25%=回檔淺、貼高點;日均額>1億=流動性可進出。
(文章口徑:utility mode 下不看「距一年低點」條件。)<br>
• <b>怎麼用</b>:這是<b>觀察清單、不是進場訊號</b> —— 修正期把名單掛著,看誰形成
VCP(波動收縮)、量縮不跌(供給枯竭);等<b>大盤轉折(見 /ftd 的 FTD 訊號)</b>時,
名單裡最先突破樞紐買點的就是 risk/reward 最好的佈局對象。<br>
⚠ 未回測;還原價口徑;成交額為 vol×收盤估算;非買賣訊號。</section>"""
    foot = (f'<p class="small">🕙 每交易日 20:50 更新 · 更新於 '
            f'{_h.escape(data.get("as_of", ""))}</p>')
    return head + "".join(body) + glossary + foot + '</body></html>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if args.html:
        data = json.load(open(LATEST, encoding="utf-8")) if os.path.exists(LATEST) else scan()
        sys.stdout.write(render_html(data))
        return
    data = build_and_save(token)
    if data.get("error"):
        print("錯誤:", data["error"]); sys.exit(1)
    st = data["market"]
    print(f"{data['date']} mode={data['mode']} N={data['n_window']} "
          f"(距高點 {st['days_since']} 日,修正 {st['drawdown']}%) "
          f"母體 {data['n_universe']} → 符合 {len(data['rows'])} 檔")
    for r in data["rows"][:15]:
        print(f"  RS{r['rs']:>4.0f} {r['code']} {r['name'][:8]:9} 現價{r['close']:>8} "
              f"{data['n_window']}日{r['win_ret']:+6.1f}% 距高-{r['dist_high']:.1f}% "
              f"額{r['money_e8']:.1f}億")


if __name__ == "__main__":
    main()

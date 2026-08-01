#!/usr/bin/env python3
"""
外資成本線估算 + 110%~140% 篩選 (tw_foreign_cost)

策略(用戶 2026-08-01):估每一檔的「外資成本」,篩出現價介於
外資成本 110%~140% 的股票 —— 外資已獲利 10~40%:高於成本(有支撐、
外資沒被套),又未過熱(<40%,不是獲利了結高風險區)。

成本估法(比照融資「遞迴成本線」XQ/三竹口徑):
  今日成本 = (昨成本 × (持股 − 淨買) + 收盤 × 淨買) ÷ 持股   (淨買 > 0 時)
  淨賣日以平均成本移除、成本不變;持股序列由「今日官方持股」+ 每日
  買賣超反推(H_{t-1} = H_t − 淨買_t)。種子 = 視窗首日收盤。
  ⚠ 收斂度 = 視窗內累積買進 ÷ 現持股:低換手(如台積電外資萬年持股)
  一年視窗算不出真實歷史成本,收斂度低的標的會標 ⚠ 或被過濾。

資料:FinMind TaiwanStockInstitutionalInvestorsBuySell(外資=Foreign_Investor
  + Foreign_Dealer_Self,逐日全市場,快取 cache/inst_day/)+
  TaiwanStockShareholding(今日外資持股+發行股數)+ 還原收盤(year_prices)。

用法:
  tw_foreign_cost.py --backfill      # 補逐日外資買賣超快取(首次 ~250 天)
  tw_foreign_cost.py --build         # 重算 + 寫 cache/foreign_cost_latest.json
  tw_foreign_cost.py --html          # debug 網頁
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
import tw_extremes as ex                     # noqa: E402

CACHE = os.path.join(HERE, "concept_momentum", "cache")
INST_DIR = os.path.join(CACHE, "inst_day")
LATEST = os.path.join(CACHE, "foreign_cost_latest.json")

RATIO_LO = 110.0     # 篩選:現價/外資成本 下限%
RATIO_HI = 140.0     # 篩選:上限%
MIN_HOLD_PCT = 5.0   # 外資持股 ≥ 發行股數 5%(外資部位要有意義)
MIN_CONV = 0.30      # 收斂度下限(視窗累積買進/現持股),低於此不列入
MIN_PRICE = 10.0     # 現價下限(排雞蛋水餃股)


def _is_common(c: str) -> bool:
    return len(c) == 4 and c.isdigit() and not c.startswith("00")


def _inst_day(date_iso: str, token: str) -> dict:
    """某交易日全市場外資買/賣(張)。{code: [buy張, sell張]}。逐日快取。
    外資 = Foreign_Investor + Foreign_Dealer_Self(官方「外資及陸資」合計)。"""
    path = os.path.join(INST_DIR, f"{date_iso.replace('-', '')}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        rows = ex._fm("TaiwanStockInstitutionalInvestorsBuySell",
                      {"start_date": date_iso, "end_date": date_iso}, token)
    except Exception:
        return {}
    out: dict = {}
    for r in rows:
        if r.get("date") != date_iso or r.get("name") not in (
                "Foreign_Investor", "Foreign_Dealer_Self"):
            continue
        c = r.get("stock_id", "")
        if not _is_common(c):
            continue
        cur = out.setdefault(c, [0.0, 0.0])
        cur[0] += (r.get("buy") or 0) / 1000       # 股 → 張
        cur[1] += (r.get("sell") or 0) / 1000
    out = {c: [round(b, 1), round(s_, 1)] for c, (b, s_) in out.items()}
    if out:
        os.makedirs(INST_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, path)
    return out


def backfill(token: str) -> int:
    dates = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    done = 0
    for i, d in enumerate(dates):
        if os.path.exists(os.path.join(INST_DIR, f"{d.replace('-', '')}.json")):
            continue
        if _inst_day(d, token):
            done += 1
        if done and done % 40 == 0:
            print(f"  inst backfill {d} ({done} new, {i+1}/{len(dates)})", flush=True)
        time.sleep(0.3)
    return done


def _holdings(token: str) -> dict:
    """今日官方外資持股 {code: [外資持股張, 發行張數]}(最近交易日)。"""
    d = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)[-1]
    rows = ex._fm("TaiwanStockShareholding",
                  {"start_date": d, "end_date": d}, token)
    out = {}
    for r in rows:
        c = r.get("stock_id", "")
        fs = r.get("ForeignInvestmentShares")
        n = r.get("NumberOfSharesIssued")
        if _is_common(c) and fs and n:
            out[c] = [round(fs / 1000), round(n / 1000)]
    return out


def build(token: str | None = None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    dates = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    hold = _holdings(token)
    names = ex._finmind_names(token)

    # 逐日載入:外資淨買(張)+ 還原收盤
    net: dict = {}       # code -> {dk: 淨買張}
    gross: dict = {}     # code -> 累積買進張
    close: dict = {}     # code -> {dk: 還原收}
    dks = []
    for d in dates:
        dk = d.replace("-", "")
        ip = os.path.join(INST_DIR, f"{dk}.json")
        if not os.path.exists(ip):
            continue
        try:
            with open(ip, encoding="utf-8") as f:
                idd = json.load(f)
        except Exception:
            continue
        pdd = ex._day_prices(d, token)
        if not pdd:
            continue
        dks.append(dk)
        for c, (b, s_) in idd.items():
            net.setdefault(c, {})[dk] = b - s_
            gross[c] = gross.get(c, 0.0) + b
        for c, v in pdd.items():
            if _is_common(c):
                close.setdefault(c, {})[dk] = v[2]
    if len(dks) < 60:
        return {"error": f"inst_day 快取不足({len(dks)} 天),先跑 --backfill"}

    rows = []
    for c, hv in hold.items():
        h_end, issued = hv
        if h_end <= 0 or issued <= 0:
            continue
        hold_pct = h_end / issued * 100
        if hold_pct < MIN_HOLD_PCT:
            continue
        cs = close.get(c, {})
        cur = cs.get(dks[-1])
        if not cur or cur < MIN_PRICE:
            continue
        nn = net.get(c, {})
        # 持股序列反推:H_{t-1} = H_t − 淨買_t
        H = [0.0] * len(dks)
        H[-1] = float(h_end)
        bad = False
        for i in range(len(dks) - 1, 0, -1):
            H[i - 1] = H[i] - nn.get(dks[i], 0.0)
            if H[i - 1] < 0:
                bad = True
                break
        if bad:
            continue                                 # 反推出負持股=資料不一致
        # 遞迴成本
        cost = None
        for i, dk in enumerate(dks):
            p = cs.get(dk)
            if p is None or H[i] <= 0:
                continue
            nb = nn.get(dk, 0.0)
            if cost is None:
                cost = p                             # 種子
                continue
            if nb > 0:
                held = max(H[i] - nb, 0.0)
                cost = (cost * held + p * nb) / (held + nb)
        if not cost or cost <= 0:
            continue
        conv = gross.get(c, 0.0) / h_end             # 收斂度
        if conv < MIN_CONV:
            continue
        ratio = cur / cost * 100
        # 近 20 日外資淨買(張)
        n20 = sum(nn.get(dk, 0.0) for dk in dks[-20:])
        rows.append({
            "code": c, "name": names.get(c, ""),
            "close": round(cur, 2), "cost": round(cost, 2),
            "ratio": round(ratio, 1),
            "hold_pct": round(hold_pct, 1),
            "hold": h_end,
            "net20": round(n20),
            "conv": round(conv, 2),
        })
    in_band = [r for r in rows if RATIO_LO <= r["ratio"] <= RATIO_HI]
    in_band.sort(key=lambda r: -r["hold_pct"])
    momo = [r for r in rows if r["ratio"] > RATIO_HI]      # 回測:140+ 表現最強
    momo.sort(key=lambda r: -r["ratio"])
    return {
        "date": dks[-1], "n_days": len(dks),
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_universe": len(rows),
        "rows": in_band,
        "rows_momo": momo,
    }


def build_and_save(token: str | None = None) -> dict:
    data = build(token)
    if not data.get("error"):
        os.makedirs(CACHE, exist_ok=True)
        tmp = LATEST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, LATEST)
    return data


# ── 呈現 ────────────────────────────────────────────────
def render_html(data: dict) -> str:
    import html as _h
    nav = __import__("site_nav").nav_html("/foreign-cost")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06);overflow-x:auto;}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;}
  th:nth-child(2),td:nth-child(2){text-align:left;}
  th{background:#eef2f7;}
  .up{color:#c0392b;} .dn{color:#0a8a3a;}
  .band{color:#fff;background:#1f6feb;border-radius:3px;padding:1px 6px;}
  .small{font-size:.85em;color:#666;}
  .note{background:#fff9ec;border:1px solid #f0dca8;border-radius:6px;
        padding:10px 14px;font-size:.86em;line-height:1.65;}
</style>"""
    d = data.get("date", "")
    fmt = f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>外資成本線 110-140%</title>{css}</head><body>{nav}'
            f'<h1>🌐 外資成本線 — 現價 110%~140% 區間 — {fmt}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'
    rows = data["rows"]
    body = [f'<section><p class="small">全市場外資持股 ≥{MIN_HOLD_PCT:.0f}% 且成本可信'
            f'(收斂度 ≥{MIN_CONV:.0%})共 {data["n_universe"]} 檔,其中'
            f'<b>現價/外資成本 ∈ [{RATIO_LO:.0f}%, {RATIO_HI:.0f}%]</b> 的 '
            f'<b>{len(rows)}</b> 檔如下(依外資持股% 排序)。'
            f'外資獲利 10~40%:高於成本=有支撐、外資未被套;未過熱=不在獲利了結高風險區。</p></section>']
    if rows:
        h = ['<section><table><thead><tr><th>#</th><th>標的</th><th>現價</th>'
             '<th>外資成本</th><th>現價/成本</th><th>外資持股%</th>'
             '<th>持股(張)</th><th>近20日淨買(張)</th><th>收斂度</th></tr></thead><tbody>']
        for i, r in enumerate(rows, 1):
            n20 = r["net20"]
            n20c = "up" if n20 > 0 else ("dn" if n20 < 0 else "")
            h.append(
                f'<tr><td data-v="{i}">{i}</td>'
                f'<td data-v="{r["code"]}">{_h.escape(r["code"])} {_h.escape(r["name"])}</td>'
                f'<td data-v="{r["close"]}">{r["close"]:g}</td>'
                f'<td data-v="{r["cost"]}">{r["cost"]:g}</td>'
                f'<td data-v="{r["ratio"]}"><span class="band">{r["ratio"]:.0f}%</span></td>'
                f'<td data-v="{r["hold_pct"]}">{r["hold_pct"]:.1f}%</td>'
                f'<td data-v="{r["hold"]}">{r["hold"]:,}</td>'
                f'<td data-v="{n20}" class="{n20c}">{n20:+,}</td>'
                f'<td data-v="{r["conv"]}">{r["conv"]:.2f}</td></tr>')
        h.append('</tbody></table></section>')
        body.append("".join(h))
    else:
        body.append('<section><p class="small">(目前無符合區間的標的)</p></section>')
    momo = data.get("rows_momo") or []
    if momo:
        h = [f'<section><h3>🚀 外資動能延續區(現價/成本 &gt; {RATIO_HI:.0f}%,共 {len(momo)} 檔)</h3>'
             '<p class="small">回測:140-180 桶 H60 超額 +13.2%、&gt;180 桶 +14.2% —— '
             '「外資大賺會調節」在樣本中不成立,獲利越多動能越強;但分布右偏、'
             '追高風險自負(依 現價/成本 排序)。</p>'
             '<table><thead><tr><th>#</th><th>標的</th><th>現價</th>'
             '<th>外資成本</th><th>現價/成本</th><th>外資持股%</th>'
             '<th>持股(張)</th><th>近20日淨買(張)</th><th>收斂度</th></tr></thead><tbody>']
        for i, r in enumerate(momo, 1):
            n20 = r["net20"]
            n20c = "up" if n20 > 0 else ("dn" if n20 < 0 else "")
            h.append(
                f'<tr><td data-v="{i}">{i}</td>'
                f'<td data-v="{r["code"]}">{_h.escape(r["code"])} {_h.escape(r["name"])}</td>'
                f'<td data-v="{r["close"]}">{r["close"]:g}</td>'
                f'<td data-v="{r["cost"]}">{r["cost"]:g}</td>'
                f'<td data-v="{r["ratio"]}"><b>{r["ratio"]:.0f}%</b></td>'
                f'<td data-v="{r["hold_pct"]}">{r["hold_pct"]:.1f}%</td>'
                f'<td data-v="{r["hold"]}">{r["hold"]:,}</td>'
                f'<td data-v="{n20}" class="{n20c}">{n20:+,}</td>'
                f'<td data-v="{r["conv"]}">{r["conv"]:.2f}</td></tr>')
        h.append('</tbody></table></section>')
        body.append("".join(h))

    bt_html = ""
    btp = os.path.join(CACHE, "foreign_cost_backtest.json")
    if os.path.exists(btp):
        try:
            bt = json.load(open(btp, encoding="utf-8"))
            rows_html = []
            for bname in ("<100", "100-110", "110-140", "140-180", ">180"):
                b = bt["buckets"].get(bname, {})
                if not b.get("n"):
                    continue
                h20, h60 = b["H20"]["exc"], b["H60"]["exc"]
                a60 = b["H60"]["abs"]
                star = " ★" if bname == "110-140" else ""
                rows_html.append(
                    f'<tr><td>{_h.escape(bname)}{star}</td><td>{b["n"]:,}</td>'
                    f'<td>{h20["mean"]:+.2f}%</td><td>{h60["mean"]:+.2f}%</td>'
                    f'<td>{a60["win"]:.0f}% / {a60["mean"]:+.1f}%</td></tr>')
            bt_html = (
                '<section><h3>🧪 回測(' + _h.escape(bt.get("window", "")) + ','
                '每5日取樣、point-in-time 成本,過濾與本頁相同)</h3>'
                '<table style="max-width:640px"><thead><tr><th>現價/成本 桶</th>'
                '<th>樣本</th><th>H20 超額</th><th>H60 超額</th>'
                '<th>H60 絕對勝率/均</th></tr></thead><tbody>'
                + "".join(rows_html) + '</tbody></table>'
                '<p class="small" style="line-height:1.6">結論:<b>單調梯度 —— 外資獲利越多的股票,'
                '之後越強</b>。★110-140 區超額轉正(H60 +3.6%,在平均個股超額 −12.6% 的年份)'
                '= 策略有效;但 <b>&gt;140 的「過熱區」其實表現最好</b>(140-180 H60 超額 +13.2%、'
                '&gt;180 +14.2%)——「外資大賺會調節」的擔心在本樣本不成立,外資獲利=動能延續。'
                '<b>&lt;100(外資被套)是全表最弱</b>(H60 超額 −14.7%),下限 110 過濾掉弱股'
                '才是本策略 edge 的主要來源;上限 140 反而切掉了最強的一群。'
                '⚠ 樣本一年(動能市 regime)、取樣重疊、分布右偏(中位數多為負,靠大贏家);'
                '梯度與單純價格動能高度相關,未必是「外資成本」獨有資訊。</p></section>')
        except Exception:
            bt_html = ""

    glossary = f"""<section class="note">📖 <b>怎麼算、怎麼看</b><br>
• <b>外資成本(遞迴成本線)</b>:比照融資成本線的 XQ 口徑 ——
「今日成本 = (昨成本 × (持股 − 淨買) + 收盤 × 淨買) ÷ 持股」,外資買進以當日
還原收盤計價、賣出以平均成本移除(不動成本)。持股序列 = 今日官方外資持股
(TaiwanStockShareholding)以每日買賣超往回反推。<br>
• <b>現價/成本 110~140% 的意義</b>:外資帳面獲利 10~40% —— 高於成本代表
外資「沒被套」、成本區常成支撐;低於 140% 代表還沒到大幅獲利了結的過熱區。
&lt;110% 貼近或跌破成本(外資自身承壓)、&gt;140% 已大賺(隨時可能調節)。<br>
• <b>收斂度</b> = 近一年外資累積買進 ÷ 現持股。<b>成本估算只可信在高收斂標的</b>:
低換手的萬年持股(如台積電,外資抱十年)一年資料算不出真實歷史成本,
故收斂度 &lt;{MIN_CONV:.0%} 的直接不列入;0.3~0.6 仍偏「近一年新倉成本」的近似。<br>
• <b>近20日淨買</b>:紅=外資近期仍在買(加碼中)、綠=在賣(調節中)。
同在 110-140% 區間,「近期還在買」與「已在調節」意義不同。<br>
• <b>門檻</b>:外資持股 ≥{MIN_HOLD_PCT:.0f}% 發行股數(部位有意義)、現價 ≥{MIN_PRICE:.0f} 元、
收斂度 ≥{MIN_CONV:.0%}。<br>
⚠ <b>限制</b>:①「外資」含外資自營與託管下的各路資金,不是單一決策者,成本是
加權平均概念 ②還原價口徑(除權息調整,與看盤軟體「原始價」外資成本線略異)
③種子=視窗首日收盤,低收斂標的種子依賴重 ④觀察工具、未回測、非買賣訊號。</section>"""
    foot = (f'<p class="small">🕙 每交易日 20:40 更新(三大法人+持股資料盤後公布)'
            f' · 更新於 {_h.escape(data.get("as_of", ""))}</p>')
    return head + "".join(body) + bt_html + glossary + foot + '</body></html>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if args.backfill:
        if not token:
            print("需要 FINMIND_TOKEN"); sys.exit(1)
        n = backfill(token)
        print(f"inst_day 新增 {n} 天")
        return
    if args.html:
        data = json.load(open(LATEST, encoding="utf-8")) if os.path.exists(LATEST) else build()
        sys.stdout.write(render_html(data))
        return
    data = build_and_save(token)
    if data.get("error"):
        print(f"錯誤: {data['error']}"); sys.exit(1)
    print(f"{data['date']} 母體 {data['n_universe']} 檔,區間內 {len(data['rows'])} 檔")
    for r in data["rows"][:12]:
        print(f"  {r['code']} {r['name'][:6]:7} 現價{r['close']:>8} 成本{r['cost']:>8} "
              f"={r['ratio']:.0f}% 持股{r['hold_pct']:.1f}% 近20日{r['net20']:+,}張 收斂{r['conv']:.2f}")


if __name__ == "__main__":
    main()

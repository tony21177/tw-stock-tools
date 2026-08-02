#!/usr/bin/env python3
"""
VCP 波動收縮型態掃描 (tw_vcp_screen) — Minervini Volatility Contraction Pattern

概念(2026-08-02 調研,各家 scanner 共識口徑):Stage 2 上升趨勢中的基底整理,
回檔一次比一次淺(如 18%→12%→6%)、量能枯竭(供給被吸收),貼近 pivot
(基底右側高點)後帶量突破 = 主升段買點。
與工具鏈關係:Utility Screen(修正期抗跌)→ VCP(型態成形)→ FTD(大盤轉折)
= Minervini 完整流程。

偵測(量化):
  前置趨勢模板:價>MA50>MA150>MA200、MA200 走揚(>20日前)、
    距一年高<25%、距一年低>+30%、年RS>=70(全市場百分位)
  VCP 本體(近 130 日基底):
    zigzag(5%)抓 swing → 回檔深度序列 2~6 段、逐段遞減(≤前段×0.85)、
    首段≤30%;末段緊縮:近10日振幅≤8% 且 低點墊高;
    量縮:近5日均量 < 50日均量×0.65;
    現價距 pivot(近15日高)≤6% = 「形成中」
  突破:收盤 > 昨日前的 pivot 且 當日量 ≥ 50日均量×1.5 = 「今日突破」→ 推播

資料:year_prices 還原高低收 + vol_day 量(自動補到 60 日)。
⚠ 未回測(林則行箱型突破台股回測為負的前車之鑑已揭露;VCP 條件不同待驗)。

用法:
  tw_vcp_screen.py --build              # 掃描 + 寫 cache
  tw_vcp_screen.py --build --telegram   # 突破日推播(去重)
  tw_vcp_screen.py --html
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
import tw_margin_scan as ms                  # noqa: E402

CACHE = os.path.join(HERE, "concept_momentum", "cache")
LATEST = os.path.join(CACHE, "vcp_latest.json")
PUSHED = os.path.join(CACHE, "vcp_pushed.json")
DEFAULT_CHAT_ID = "-5229750819"

BASE_LOOKBACK = 130   # 基底觀察視窗(交易日)
ZZ_THR = 0.05         # zigzag 擺動門檻
MAX_C1 = 0.30         # 首段回檔上限
SHRINK = 0.85         # 遞減:後段 ≤ 前段 × 0.85
FINAL_TIGHT = 0.08    # 末段:近10日振幅上限
VOL_DRY = 0.65        # 量縮:vol5 < vol50 × 0.65
PIVOT_DIST = 0.06     # 形成中:距 pivot ≤6%
BRK_VOL = 1.5         # 突破量:≥ vol50 × 1.5
RS_MIN = 70           # 年RS 門檻


def _fut_star(code):
    try:
        import tw_stock_futures as _sf
        return " ★" if code in _sf.fut_stock_set() else ""
    except Exception:
        return ""


def _zigzag(highs, lows, thr=ZZ_THR):
    """回傳 swings=[(kind,idx,price)],kind H/L 交替。"""
    sw = []
    mode = None            # 'up' 尋高 / 'down' 尋低
    ext_i, ext_p = 0, highs[0]
    for i in range(1, len(highs)):
        if mode in (None, 'up'):
            if highs[i] > ext_p:
                ext_i, ext_p = i, highs[i]
            if lows[i] < ext_p * (1 - thr):
                sw.append(('H', ext_i, ext_p))
                mode = 'down'
                ext_i, ext_p = i, lows[i]
        elif mode == 'down':
            if lows[i] < ext_p:
                ext_i, ext_p = i, lows[i]
            if highs[i] > ext_p * (1 + thr):
                sw.append(('L', ext_i, ext_p))
                mode = 'up'
                ext_i, ext_p = i, highs[i]
        if mode is None and lows[i] < highs[0] * (1 - thr):
            mode = 'down'
            ext_i, ext_p = i, lows[i]
    sw.append((mode == 'down' and 'L' or 'H', ext_i, ext_p))
    return sw


def _detect_vcp(highs, lows, closes):
    """對近 BASE_LOOKBACK 日偵測 VCP。回 None 或
    {depths(%列表), pivot, tight(近10日振幅%), higher_low(bool)}"""
    h = highs[-BASE_LOOKBACK:]
    l = lows[-BASE_LOOKBACK:]
    sw = _zigzag(h, l)
    # 回檔段:H→L 深度
    depths = []
    lows_seq = []
    for i in range(len(sw) - 1):
        if sw[i][0] == 'H' and sw[i + 1][0] == 'L':
            d = (sw[i][2] - sw[i + 1][2]) / sw[i][2]
            depths.append(d)
            lows_seq.append(sw[i + 1][2])
    if len(depths) < 2:
        return None
    depths = depths[-6:]
    lows_seq = lows_seq[-6:]
    if depths[0] > MAX_C1:
        return None
    for a, b in zip(depths, depths[1:]):
        if b > a * SHRINK:
            return None
    if len(lows_seq) >= 2 and lows_seq[-1] <= lows_seq[-2]:
        return None                              # 低點須墊高
    tight = (max(h[-10:]) - min(l[-10:])) / max(h[-10:])
    if tight > FINAL_TIGHT:
        return None
    pivot = max(h[-15:])
    return {"depths": [round(d * 100, 1) for d in depths],
            "pivot": round(pivot, 2),
            "tight": round(tight * 100, 1),
            }


def _rs_pct(all_closes: dict, n: int = 250) -> dict:
    """全市場年RS百分位(IBD 加權)。"""
    import tw_utility_screen as us
    scores = {}
    for c, cs in all_closes.items():
        s = us._rs_score(cs, min(n, len(cs) - 1)) if len(cs) > 60 else None
        if s is not None:
            scores[c] = s
    ranked = sorted(scores, key=lambda x: scores[x])
    return {c: round((i + 1) / len(ranked) * 99, 1)
            for i, c in enumerate(ranked)}


def scan(token: str | None = None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    dates = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    names = ex._finmind_names(token)
    closes: dict = {}
    highs: dict = {}
    lows: dict = {}
    for d in dates:
        dp = ex._day_prices(d, token)
        if not dp:
            continue
        for c, v in dp.items():
            if not (len(c) == 4 and c.isdigit() and not c.startswith("00")):
                continue
            highs.setdefault(c, []).append(v[0])
            lows.setdefault(c, []).append(v[1])
            closes.setdefault(c, []).append(v[2])
    # 量:近 60 日(張)
    vols: dict = {}
    for d in dates[-60:]:
        vd = ms._vol_day(d, token)
        for c, v in vd.items():
            if c in closes:
                vols.setdefault(c, []).append(v)
    rs = _rs_pct(closes)
    # utility 名單重合
    try:
        with open(os.path.join(CACHE, "utility_screen_latest.json"),
                  encoding="utf-8") as f:
            uset = {r["code"] for r in json.load(f).get("rows", [])}
    except Exception:
        uset = set()

    forming, breakout = [], []
    for c, cs in closes.items():
        if len(cs) < 205 or rs.get(c, 0) < RS_MIN:
            continue
        cur = cs[-1]
        ma50 = sum(cs[-50:]) / 50
        ma150 = sum(cs[-150:]) / 150
        ma200 = sum(cs[-200:]) / 200
        ma200_prev = sum(cs[-220:-20]) / 200
        if not (cur > ma50 > ma150 > ma200 and ma200 > ma200_prev):
            continue
        hi52 = max(highs[c][-250:])
        lo52 = min(lows[c][-250:])
        if cur < hi52 * 0.75 or cur < lo52 * 1.30:
            continue
        vv = vols.get(c, [])
        if len(vv) < 50:
            continue
        vol50 = sum(vv[-50:]) / 50
        vol5 = sum(vv[-5:]) / 5
        if vol50 <= 0:
            continue
        det = _detect_vcp(highs[c], lows[c], cs)
        if not det:
            continue
        row = {
            "code": c, "name": names.get(c, "") + _fut_star(c),
            "close": round(cur, 2), "rs": rs.get(c),
            "depths": det["depths"], "tight": det["tight"],
            "pivot": det["pivot"],
            "dist_pivot": round((1 - cur / det["pivot"]) * 100, 1),
            "vol_dry": round(vol5 / vol50, 2),
            "in_utility": c in uset,
        }
        # 突破:收盤 > 昨日前 pivot 且 今量 ≥ 1.5×vol50
        pivot_prev = max(highs[c][-16:-1])
        if cur > pivot_prev and vv[-1] >= vol50 * BRK_VOL:
            row["brk_vol_x"] = round(vv[-1] / vol50, 1)
            breakout.append(row)
        elif (1 - cur / det["pivot"]) <= PIVOT_DIST and vol5 < vol50 * VOL_DRY:
            forming.append(row)
    forming.sort(key=lambda r: (-r["in_utility"], -r["rs"]))
    breakout.sort(key=lambda r: -r["rs"])
    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": dates[-1] if dates else "",
        "n_universe": len(closes),
        "forming": forming, "breakout": breakout,
    }


def _warm(codes, token):
    try:
        import tw_utility_screen as us
        us._warm_kline(codes, token)
    except Exception:
        pass


def build_and_save(token: str | None = None) -> dict:
    data = scan(token)
    if not data.get("error"):
        tmp = LATEST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, LATEST)
        _warm([r["code"] for r in data["forming"] + data["breakout"]],
              token or os.environ.get("FINMIND_TOKEN", ""))
    return data


def push_breakouts(data: dict, bot: str, chat_id: str):
    import urllib.parse
    import urllib.request
    try:
        with open(PUSHED, encoding="utf-8") as f:
            pushed = json.load(f)
    except Exception:
        pushed = {}
    fresh = [r for r in data["breakout"]
             if pushed.get(r["code"]) != data["date"]]
    if not fresh:
        return
    lines = [f"🚀 VCP 突破 pivot {data['date']}", ""]
    for r in fresh:
        lines.append(
            f"{r['code']} {r['name']}  {r['close']}(RS {r['rs']:.0f})\n"
            f"  收縮 {'→'.join(str(x) + '%' for x in r['depths'])} "
            f"| 突破量 {r.get('brk_vol_x', 0)}x"
            + (" | 🛡抗跌名單" if r["in_utility"] else ""))
    lines += ["", "⚠ 未回測、非買賣訊號。詳: "
              + __import__("site_nav").public_url("/vcp")]
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": "\n".join(lines)}).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot}/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=30) as r:
            if json.load(r).get("ok"):
                for x in fresh:
                    pushed[x["code"]] = data["date"]
                with open(PUSHED, "w", encoding="utf-8") as f:
                    json.dump(pushed, f)
                print(f"已推 {len(fresh)} 檔 VCP 突破")
    except Exception as e:
        print(f"推播失敗: {e}", file=sys.stderr)


def render_html(data: dict) -> str:
    import html as _h
    nav = __import__("site_nav").nav_html("/vcp")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06);overflow-x:auto;}
  .small{font-size:.85em;color:#666;}
  .note{background:#fff9ec;border:1px solid #f0dca8;border-radius:6px;
        padding:10px 14px;font-size:.86em;line-height:1.65;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>VCP 波動收縮</title>{css}</head><body>{nav}'
            f'<h1>🌀 VCP 波動收縮型態(Minervini)— '
            f'{_h.escape(data.get("date", ""))}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'

    def cards(rows, kind):
        if not rows:
            return '<section><p class="small">(無)</p></section>'
        out = ['<section><div style="display:grid;'
               'grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px">']
        for r in rows:
            seq = "→".join(f"{x:g}%" for x in r["depths"])
            extra = (f'<span style="background:#0e2b1d;color:#8ce6b6;border-radius:3px;'
                     f'padding:0 5px">🛡抗跌</span>' if r["in_utility"] else "")
            brk = (f'<span style="background:#63262b;color:#ff9b9b;border-radius:3px;'
                   f'padding:0 5px">量{r["brk_vol_x"]}x</span>'
                   if kind == "brk" else
                   f'<span style="color:#8b98a9">乾涸{r["vol_dry"]:.2f}</span>')
            out.append(
                f'<div data-kx="{r["code"]}" style="background:#151b23;'
                f'border:1px solid #223041;border-radius:8px;padding:6px;cursor:pointer">'
                f'<canvas class="usmini" data-code="{r["code"]}" '
                f'style="width:100%;height:110px;display:block"></canvas>'
                f'<div style="font:600 12px monospace;color:#dfe6ee;margin-top:4px">'
                f'{_h.escape(r["code"])} {_h.escape(r["name"])}</div>'
                f'<div style="font:10px monospace;margin-top:2px;display:flex;gap:6px;flex-wrap:wrap">'
                f'<span style="background:#1f6feb;color:#fff;border-radius:3px;padding:0 5px">RS {r["rs"]:.0f}</span>'
                f'<span style="background:#5c4c1d;color:#e6c56a;border-radius:3px;padding:0 5px">{seq}</span>'
                f'{brk}{extra}</div></div>')
        out.append('</div></section>')
        return "".join(out)

    body = [
        f'<section><p class="small">前置趨勢模板:價>MA50>MA150>MA200(MA200 走揚)'
        f'+ 距一年高<25% + 距一年低>+30% + 年RS≥{RS_MIN}。VCP:zigzag 5% 抓收縮段 '
        f'2~6 段逐段遞減(≤前段×{SHRINK})、首段≤{MAX_C1:.0%}、低點墊高、'
        f'近10日振幅≤{FINAL_TIGHT:.0%}、量縮 vol5<vol50×{VOL_DRY}。'
        f'母體 {data["n_universe"]} 檔。點卡片看大圖。'
        f'⚠ <b>未回測</b>(林則行箱型突破台股回測為負;VCP 條件不同待驗)、非買賣訊號。</p></section>',
        f'<h3>🚀 今日突破 pivot(帶量 ≥{BRK_VOL}×50日均量,{len(data["breakout"])} 檔)</h3>',
        cards(data["breakout"], "brk"),
        f'<h3>🌀 VCP 形成中(貼 pivot ≤{PIVOT_DIST:.0%} 且量縮,{len(data["forming"])} 檔,🛡=同在抗跌名單)</h3>',
        cards(data["forming"], "form"),
    ]
    mini_js = """<script>
(function(){
  var UP='#ff4d4d',DN='#2ecc8f';
  function sma(a,n){var o=[],s=0;for(var i=0;i<a.length;i++){s+=a[i];if(i>=n)s-=a[i-n];o.push(i>=n-1?s/n:null);}return o;}
  function mini(cv,rows){
    rows=rows.slice(-120);
    var dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
    cv.width=W*dpr;cv.height=H*dpr;
    var g=cv.getContext('2d');g.scale(dpr,dpr);
    var n=rows.length,cw=W/n,bw=Math.max(1,cw*0.7);
    var pH=H*0.74,vT=H*0.78,vH=H*0.22;
    var hi=-1e18,lo=1e18;
    rows.forEach(function(r){hi=Math.max(hi,r[2]);lo=Math.min(lo,r[3]);});
    var pr=hi-lo||1;
    var Y=function(p){return 2+(pH-4)*(1-(p-lo)/pr);};
    var X=function(i){return i*cw+cw/2;};
    rows.forEach(function(r,i){
      var up=r[4]>=r[1];g.strokeStyle=g.fillStyle=up?UP:DN;var x=X(i);
      g.beginPath();g.moveTo(x,Y(r[2]));g.lineTo(x,Y(r[3]));g.stroke();
      var y1=Y(Math.max(r[1],r[4])),y2=Y(Math.min(r[1],r[4]));
      g.fillRect(x-bw/2,y1,bw,Math.max(1,y2-y1));});
    [[20,'#f5d34c'],[60,'#4cc2ff']].forEach(function(mc){
      var m=sma(rows.map(function(r){return r[4];}),mc[0]);
      g.strokeStyle=mc[1];g.lineWidth=1;g.beginPath();var b=false;
      m.forEach(function(v,i){if(v==null)return;var y=Y(v);
        b?g.lineTo(X(i),y):g.moveTo(X(i),y);b=true;});
      g.stroke();});
    var vm=0;rows.forEach(function(r){vm=Math.max(vm,r[5]);});vm=vm||1;
    rows.forEach(function(r,i){g.fillStyle=r[4]>=r[1]?UP:DN;
      var h=vH*r[5]/vm;g.fillRect(X(i)-bw/2,vT+vH-h,bw,h);});
  }
  var q=[].slice.call(document.querySelectorAll('canvas.usmini')),act=0;
  function next(){
    if(!q.length||act>=5)return;
    var cv=q.shift();act++;
    fetch('/api/kline/'+cv.getAttribute('data-code'))
      .then(function(r){return r.json();})
      .then(function(d){if(d.rows&&d.rows.length)mini(cv,d.rows);})
      .catch(function(){})
      .then(function(){act--;next();});
    next();
  }
  next();
})();
</script>"""
    glossary = f"""<section class="note">📖 <b>VCP 白話</b><br>
• <b>型態邏輯</b>:上升趨勢中的整理,回檔一次比一次淺(卡片上的「18→12→6%」
就是收縮序列)= 願意賣的人越來越少;<b>量縮(乾涸值 = 近5日均量/50日均量)</b>
= 供給枯竭;最後貼著 <b>pivot</b>(基底右側高點)—— 帶量突破就是買點。<br>
• <b>兩個清單</b>:「今日突破」= 收盤過 pivot 且量 ≥1.5×50日均量(盤後確認,隔日留意
續強或回測 pivot);「形成中」= 距 pivot ≤{PIVOT_DIST:.0%} 且量已乾涸(觀察名單,
等突破)。🛡 = 同時在抗跌領頭羊(/utility-screen)名單 = 修正期抗跌 + VCP,最強組合。<br>
• <b>與大盤配合</b>:Minervini 流程 = 修正期用 Utility Screen 建名單 → 等 /ftd 的
FTD 大盤轉折 → 名單中 VCP 突破者為首選。大盤修正未止時,突破失敗率高。<br>
⚠ <b>未回測</b>;zigzag 5% 為近似偵測(極緊的早期收縮可能漏抓);還原價口徑;
非買賣訊號。</section>"""
    foot = (f'<p class="small">🕙 每交易日 21:00 更新,突破日推 Telegram · 更新於 '
            f'{_h.escape(data.get("as_of", ""))}</p>')
    return head + "".join(body) + mini_js + glossary + foot + '</body></html>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
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
    print(f"{data['date']} 母體 {data['n_universe']} → 突破 {len(data['breakout'])} 檔 / "
          f"形成中 {len(data['forming'])} 檔")
    for r in data["breakout"]:
        print(f"  🚀 {r['code']} {r['name'][:8]:9} RS{r['rs']:.0f} "
              f"收縮 {'→'.join(str(x)+'%' for x in r['depths'])} 量{r.get('brk_vol_x')}x"
              + (" 🛡" if r['in_utility'] else ""))
    for r in data["forming"][:15]:
        print(f"  🌀 {r['code']} {r['name'][:8]:9} RS{r['rs']:.0f} "
              f"收縮 {'→'.join(str(x)+'%' for x in r['depths'])} 距pivot -{r['dist_pivot']}% "
              f"乾涸{r['vol_dry']}" + (" 🛡" if r['in_utility'] else ""))
    if args.telegram:
        bot = os.environ.get("TG_BOT_TOKEN", "")
        if bot:
            push_breakouts(data, bot, args.chat_id)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""全站統一導航列 (site_nav)

每個工具頁的 render_html 都 import 這裡的 nav_html(),取代各自手寫的
<nav>(舊況:每頁連結子集不同、futures-basis/adr-premium 甚至沒 nav)。
新增工具頁時只要改 NAV_LINKS 一處,全站同步。

用法:
    from site_nav import nav_html
    nav = nav_html("/margin-scan")   # 當前頁會顯示為粗體、不可點
"""

# (href, 顯示名) — 順序即顯示順序;分組用 None 當分隔點(顯示 ·)
NAV_LINKS = [
    ("/", "🏠 首頁"),
    ("/market-tomorrow", "🌏 明天大盤"),
    ("/ftd", "🚀 FTD"),
    ("/option-flow", "📊 選擇權法人"),
    ("/margin-scan", "💥 融資斷頭潮"),
    ("/extremes", "📊 一年高低"),
    ("/seasonality", "📅 月份季節性"),
    ("/stock-futures", "🔥 個股期"),
    ("/lin-matrix", "📐 林則行"),
    ("/futures-basis", "📐 期貨基差"),
    ("/adr-premium", "🇺🇸 ADR"),
    ("/warrant-signal", "🎫 權證"),
    ("/money-flow", "💰 資金流"),
    ("/chip-price", "🧬 籌碼價量"),
    ("/intraday-sim", "📉 盤中模擬"),
]

_CSS = (
    '<style>nav.site{font-size:.82em;line-height:2;margin-bottom:6px}'
    'nav.site a{margin-right:10px;color:#0066cc;text-decoration:none;'
    'white-space:nowrap}nav.site a:hover{text-decoration:underline}'
    'nav.site b{margin-right:10px;color:#222;white-space:nowrap}</style>'
)

# 全站統一版型 —「金融終端機」深色主題(注入於 <body> 內、晚於各頁 head
# style → 同權重下勝出;inline style 需 !important 才蓋)。
# 色票:漲 #ff6b6b / 跌 #34c98e(dataviz 驗證器:對 #0d1117 底對比 ≥3:1 通過;
# 紅綠對 deutan 色盲不可分為台股語意色之必然,第二編碼=全站數字都帶 +/− 與 ▲▼)。
_SITE_CSS = """<style>
:root{--bg:#0d1117;--card:#151b23;--card2:#1a2230;--line:#223041;
  --ink:#dfe6ee;--ink2:#8b98a9;--ink3:#5d6b7d;--acc:#4cc2ff;
  --up:#ff6b6b;--dn:#34c98e}
html{background:var(--bg)}
body{max-width:1100px;background:var(--bg);color:var(--ink);
  font-variant-numeric:tabular-nums}
h1,h2,h3,h4,caption{color:#eef3f8}
h1{letter-spacing:.5px;padding-bottom:8px;position:relative}
h1:after{content:"";position:absolute;left:0;bottom:0;width:120px;height:3px;
  border-radius:2px;background:linear-gradient(90deg,var(--acc),transparent)}
a{color:var(--acc)}
section{background:var(--card);border:1px solid var(--line);
  box-shadow:none;border-radius:10px}
table{font-variant-numeric:tabular-nums}
table thead th{position:sticky;top:0;z-index:2;background:var(--card2);
  color:#9fb0c3;letter-spacing:.4px;border-bottom:1px solid #2e405a;
  box-shadow:none}
th,td{border-bottom:1px solid #1c2634}
tbody tr:hover td{background:rgba(76,194,255,.05)}
.up{color:var(--up)}.dn{color:var(--dn)}
.small,.meta{color:var(--ink2)}
.note{background:#1c1910;border-color:#3d3417;color:#cfc49e}
.note b,.note strong{color:#e8dcae}
/* 狀態徽章(ftd/option-flow)深色版 */
.sigb{background:#0e2b1d;border-color:#1d5c3c;color:#8ce6b6}
.sigs{background:#2f1416;border-color:#63262b;color:#ff9b9b}
.signone{background:var(--card2);border-color:var(--line);color:var(--ink2)}
.st-up{background:#0e2b1d;color:#5fd598;border-color:#1d5c3c}
.st-corr{background:#2f1416;color:#ff8f8f;border-color:#63262b}
.st-rally{background:#2b230c;color:#e6c56a;border-color:#5c4c1d}
.ok{color:var(--dn)}.bad{color:var(--up)}
.hl{background:#26301c}
/* 統一導航:sticky 玻璃列 */
nav.site{position:sticky;top:0;z-index:40;background:rgba(13,17,23,.86);
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);padding:6px 10px;margin:0 -10px 12px;
  border-radius:0 0 10px 10px}
@media (max-width:640px){nav.site{position:static}}
nav.site a{color:#9fb0c3}nav.site a:hover{color:var(--acc);text-decoration:none}
nav.site b{color:var(--acc);text-shadow:0 0 12px rgba(76,194,255,.45)}
nav a{color:var(--acc)}
/* 表格互動 */
.adrag{cursor:grab}.adrag.grabbing{cursor:grabbing}
.dragx{cursor:grab}
th[data-sortable]{cursor:pointer;user-select:none}
th[data-sortable]:hover{filter:brightness(1.25)}
th .sarr,th .ar{color:var(--acc);font-size:.8em;margin-left:2px}
/* 表單 */
input,select,textarea{background:var(--card2);color:var(--ink);
  border:1px solid var(--line);border-radius:6px;padding:5px 8px}
button{background:#1f6feb;color:#fff;border:none;border-radius:6px;
  padding:6px 12px;cursor:pointer}
button:hover{background:#2e7ef5}
/* 捲軸 */
::-webkit-scrollbar{height:9px;width:9px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:#2b3a4f;border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:#3b4f6b}
::selection{background:rgba(76,194,255,.3)}
/* 頁面自帶的白底 inline 元件(黃條提示等)轉深色卡 */
section[style*="fff8e1"],div[style*="fff8e1"]{
  background:#2b230c !important;border-color:#5c4c1d !important;color:#e6c56a}
</style>"""

# 自動表格增強:①每個 th 可點排序(再點反向;已有自訂 onclick 的表跳過)
# ②寬到會橫向捲動的容器 → 滑鼠按住拖拉 ③favicon
_ENHANCE_JS = """<script>
(function(){
function cellVal(td){
  var v=td.getAttribute('data-v');
  var t=(v!==null&&v!==undefined?String(v):td.textContent).trim();
  if(/^\\d{4}[-/]\\d{2}[-/]\\d{2}/.test(t)) return {d:t};      // 日期字串排序
  var s=t.replace(/[−–]/g,'-').replace(/[^0-9.eE+-]/g,'');
  var f=parseFloat(s);
  return isNaN(f)?{s:t.toLowerCase()}:{n:f};
}
function cmp(a,b){
  if(a.n!==undefined&&b.n!==undefined)return a.n-b.n;
  if(a.d!==undefined&&b.d!==undefined)return a.d<b.d?-1:(a.d>b.d?1:0);
  if(a.n!==undefined)return -1; if(b.n!==undefined)return 1;
  var x=a.d||a.s||'', y=b.d||b.s||'';
  return x<y?-1:(x>y?1:0);
}
function makeSortable(tb){
  var thead=tb.tHead; if(!thead||!tb.tBodies.length)return;
  var ths=thead.rows[thead.rows.length-1].cells;
  for(let i=0;i<ths.length;i++){
    var th=ths[i];
    if(th.getAttribute('onclick'))return;          // 頁面自帶排序(整表跳過)
    th.setAttribute('data-sortable','1');
    var arr=document.createElement('span');arr.className='sarr';th.appendChild(arr);
    th.addEventListener('click',(function(col){return function(){
      var body=tb.tBodies[0];
      var rows=Array.prototype.slice.call(body.rows);
      var dir=tb._scol===col&&tb._sdir==='asc'?'desc':'asc';
      tb._scol=col;tb._sdir=dir;
      rows.sort(function(r1,r2){
        var c=cmp(cellVal(r1.cells[col]||{textContent:''}),cellVal(r2.cells[col]||{textContent:''}));
        return dir==='asc'?c:-c;});
      rows.forEach(function(r){body.appendChild(r);});
      Array.prototype.forEach.call(ths,function(t){var s=t.querySelector('.sarr');if(s)s.textContent='';});
      var s=ths[col].querySelector('.sarr');if(s)s.textContent=dir==='asc'?'▲':'▼';
    };})(i));
  }
}
function makeDraggable(el){
  if(el.dataset.adrag||el.classList.contains('dragx'))return;   // 頁面自帶拖拉跳過
  el.dataset.adrag='1';el.classList.add('adrag');
  var down=false,sx,sl,moved=false;
  el.addEventListener('mousedown',function(e){if(e.button!==0)return;
    down=true;moved=false;sx=e.pageX;sl=el.scrollLeft;el.classList.add('grabbing');});
  window.addEventListener('mousemove',function(e){if(!down)return;
    var dx=e.pageX-sx; if(Math.abs(dx)>4)moved=true; el.scrollLeft=sl-dx;});
  window.addEventListener('mouseup',function(){down=false;el.classList.remove('grabbing');});
  el.addEventListener('click',function(e){if(moved){e.stopPropagation();e.preventDefault();moved=false;}},true);
}
function boot(){
  var nv=document.querySelector('nav.site');
  if(nv)document.documentElement.style.setProperty('--navh',nv.offsetHeight+'px');
  window.addEventListener('resize',function(){
    if(nv)document.documentElement.style.setProperty('--navh',nv.offsetHeight+'px');});
  // sticky th 的 top:內層捲動容器裡=0(黏容器頂);直接在頁面上=nav 高度
  // (sticky top 相對「最近的捲動容器」而非視窗;overflow-x:auto 的祖先
  //  也算捲動容器 → top:0 安全退化為不黏,不會浮在表中間)
  document.querySelectorAll('table').forEach(function(t){
    if(!t.tHead)return;
    var p=t.parentElement,inner=false;
    while(p&&p!==document.body){
      var s=getComputedStyle(p);
      if(/(auto|scroll)/.test(s.overflow+s.overflowX+s.overflowY)){inner=true;break;}
      p=p.parentElement;
    }
    var stickyNav=nv&&getComputedStyle(nv).position==='sticky';
    var top=inner?'0px':(stickyNav?'var(--navh,36px)':'0px');
    t.querySelectorAll('thead th').forEach(function(el){el.style.top=top;});
  });
  document.querySelectorAll('table').forEach(makeSortable);
  document.querySelectorAll('section,div').forEach(function(el){
    if(el.scrollWidth>el.clientWidth+8)makeDraggable(el);});
  if(!document.querySelector('link[rel="icon"]')){
    var l=document.createElement('link');l.rel='icon';
    l.href='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📈</text></svg>';
    document.head.appendChild(l);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>"""


# 對外網址(推播訊息用;localhost 在手機上點不開)。ngrok 靜態域名,
# 可用 env PUBLIC_BASE_URL 覆蓋。
import os as _os

PUBLIC_BASE = _os.environ.get(
    "PUBLIC_BASE_URL", "https://shudder-attention-musky.ngrok-free.dev")


def public_url(path: str = "/") -> str:
    """推播訊息用的公開網址(手機可開)。"""
    return PUBLIC_BASE.rstrip("/") + path


def nav_html(current: str | None = None) -> str:
    """統一導航列 + 全站樣式覆蓋(寬度/深色模式)+ 表格增強(排序/拖拉)+ favicon。
    current=當前頁 href(顯示粗體不可點)。"""
    parts = []
    for href, label in NAV_LINKS:
        if href == current:
            parts.append(f"<b>{label}</b>")
        else:
            parts.append(f'<a href="{href}">{label}</a>')
    return (_CSS + _SITE_CSS + '<nav class="site">' + " ".join(parts)
            + "</nav>" + _ENHANCE_JS)

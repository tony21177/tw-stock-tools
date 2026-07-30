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

# 全站統一版型 + 深色模式(注入於 <body> 內、晚於各頁 head style → 同權重下勝出)
_SITE_CSS = """<style>
body{max-width:1100px}
table thead th{position:sticky;top:0;z-index:2;background:#eef2f7}
.adrag{cursor:grab}.adrag.grabbing{cursor:grabbing}
th[data-sortable]{cursor:pointer;user-select:none}
th[data-sortable]:hover{filter:brightness(.93)}
th .sarr{color:#0066cc;font-size:.8em;margin-left:2px}
@media (prefers-color-scheme: dark){
  body{background:#131518;color:#d4d4d4}
  section{background:#1c1f24;box-shadow:none}
  table thead th{background:#242a31;color:#c8cdd3}
  th,td{border-bottom-color:#2c3138 !important}
  h1,h2,h3,caption{color:#e6e6e6}
  a{color:#5da9ff} nav.site a{color:#5da9ff} nav.site b{color:#eee}
  .note{background:#25200f;border-color:#4a4020;color:#d3ccae}
  .small,.meta{color:#8a8f96}
}
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

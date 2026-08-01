/* 全站個股 K 線彈窗 (2026-08-01)
 * 點任何「4碼代號 + 名稱」的表格格子 → 彈窗:日K + MA5/20/60、VOL、MACD(12,26,9)
 * 深色終端機風、台股慣例紅漲綠跌。資料 /api/kline/<code>(FinMind 原始日K)。 */
(function () {
  var CSS = [
    '.klx-mask{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:900;',
    ' display:flex;align-items:center;justify-content:center}',
    '.klx-box{background:#10151c;border:1px solid #2b3a4f;border-radius:12px;',
    ' width:min(96vw,860px);max-height:92vh;padding:10px 12px;box-shadow:0 8px 40px rgba(0,0,0,.6)}',
    '.klx-head{display:flex;align-items:center;gap:10px;color:#dfe6ee;',
    ' font:600 15px -apple-system,"Microsoft JhengHei",sans-serif;padding:2px 2px 6px}',
    '.klx-close{margin-left:auto;cursor:pointer;background:#1a2230;border:1px solid #2b3a4f;',
    ' color:#9fb0c3;border-radius:6px;padding:2px 10px;font-size:14px}',
    '.klx-close:hover{color:#4cc2ff}',
    '.klx-leg{font:11px/1.6 -apple-system,"Microsoft JhengHei",monospace;padding:0 2px}',
    'td.klx-c{cursor:pointer}td.klx-c:hover{background:rgba(76,194,255,.10)!important}',
    '.klx-err{color:#ff9b9b;padding:30px;text-align:center}'
  ].join('');
  var st = document.createElement('style'); st.textContent = CSS;
  document.head.appendChild(st);

  var UP = '#ff4d4d', DN = '#2ecc8f', INK = '#dfe6ee', MUT = '#5d6b7d';
  var MA_C = { 5: '#f5d34c', 20: '#c47bff', 60: '#4cc2ff' };

  function ema(arr, n) {
    var k = 2 / (n + 1), out = [], prev = null;
    for (var i = 0; i < arr.length; i++) {
      prev = prev === null ? arr[i] : arr[i] * k + prev * (1 - k);
      out.push(prev);
    }
    return out;
  }
  function sma(arr, n) {
    var out = [], s = 0;
    for (var i = 0; i < arr.length; i++) {
      s += arr[i]; if (i >= n) s -= arr[i - n];
      out.push(i >= n - 1 ? s / n : null);
    }
    return out;
  }

  function draw(cv, rows) {
    var dpr = window.devicePixelRatio || 1;
    var W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    var g = cv.getContext('2d'); g.scale(dpr, dpr);
    g.clearRect(0, 0, W, H);
    var padR = 52, padL = 4;
    var kH = H * 0.56, vH = H * 0.16, mH = H * 0.22, gap = H * 0.02;
    var vT = kH + gap, mT = kH + vH + gap * 2;
    var n = rows.length;
    var cw = (W - padR - padL) / n, bw = Math.max(1, cw * 0.62);
    var X = function (i) { return padL + i * cw + cw / 2; };

    var closes = rows.map(function (r) { return r[4]; });
    var vols = rows.map(function (r) { return r[5]; });
    var ma5 = sma(closes, 5), ma20 = sma(closes, 20), ma60 = sma(closes, 60);
    var e12 = ema(closes, 12), e26 = ema(closes, 26);
    var dif = closes.map(function (_, i) { return e12[i] - e26[i]; });
    var dea = ema(dif, 9);
    var osc = dif.map(function (d, i) { return d - dea[i]; });

    // ── K 線面板 ──
    var hi = -1e18, lo = 1e18;
    rows.forEach(function (r) { hi = Math.max(hi, r[2]); lo = Math.min(lo, r[3]); });
    [ma5, ma20, ma60].forEach(function (m) {
      m.forEach(function (v) { if (v != null) { hi = Math.max(hi, v); lo = Math.min(lo, v); } });
    });
    var pr = hi - lo || 1;
    var Y = function (p) { return 8 + (kH - 16) * (1 - (p - lo) / pr); };
    g.strokeStyle = '#1c2634'; g.lineWidth = 1; g.font = '10px monospace';
    [lo, lo + pr / 3, lo + pr * 2 / 3, hi].forEach(function (p) {
      var y = Y(p);
      g.beginPath(); g.moveTo(padL, y); g.lineTo(W - padR, y); g.stroke();
      g.fillStyle = MUT; g.fillText(p >= 100 ? p.toFixed(0) : p.toFixed(2), W - padR + 4, y + 3);
    });
    rows.forEach(function (r, i) {
      var o = r[1], h = r[2], l = r[3], c = r[4];
      var up = c >= o; g.strokeStyle = g.fillStyle = up ? UP : DN;
      var x = X(i);
      g.beginPath(); g.moveTo(x, Y(h)); g.lineTo(x, Y(l)); g.stroke();
      var y1 = Y(Math.max(o, c)), y2 = Y(Math.min(o, c));
      g.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
    });
    function line(m, col, top, hgt, ylo, yr) {
      g.strokeStyle = col; g.lineWidth = 1.2; g.beginPath();
      var began = false;
      m.forEach(function (v, i) {
        if (v == null) return;
        var y = top + (hgt - 10) * (1 - (v - ylo) / yr) + 5;
        began ? g.lineTo(X(i), y) : g.moveTo(X(i), y); began = true;
      });
      g.stroke();
    }
    line(ma5, MA_C[5], 3, kH, lo, pr); line(ma20, MA_C[20], 3, kH, lo, pr);
    line(ma60, MA_C[60], 3, kH, lo, pr);

    // ── VOL 面板 ──
    var vmax = Math.max.apply(null, vols) || 1;
    var vy = function (v) { return vT + (vH - 4) * (1 - v / vmax) + 2; };
    rows.forEach(function (r, i) {
      g.fillStyle = r[4] >= r[1] ? UP : DN;
      var x = X(i);
      g.fillRect(x - bw / 2, vy(r[5]), bw, vT + vH - vy(r[5]));
    });
    var v5 = sma(vols, 5), v20 = sma(vols, 20);
    line(v5, MA_C[5], vT, vH, 0, vmax); line(v20, MA_C[20], vT, vH, 0, vmax);
    g.fillStyle = MUT;
    g.fillText((vmax >= 10000 ? (vmax / 1000).toFixed(0) + 'k' : vmax.toFixed(0)), W - padR + 4, vT + 10);

    // ── MACD 面板 ──
    var mhi = 0;
    dif.forEach(function (v, i) {
      mhi = Math.max(mhi, Math.abs(v), Math.abs(dea[i]), Math.abs(osc[i]));
    });
    mhi = mhi || 1;
    var my = function (v) { return mT + (mH - 8) * (0.5 - v / (2 * mhi)) + 4; };
    g.strokeStyle = '#1c2634'; g.beginPath();
    g.moveTo(padL, my(0)); g.lineTo(W - padR, my(0)); g.stroke();
    osc.forEach(function (v, i) {
      g.fillStyle = v >= 0 ? UP : DN;
      var x = X(i), y0 = my(0), y1 = my(v);
      g.fillRect(x - bw / 2, Math.min(y0, y1), bw, Math.max(1, Math.abs(y1 - y0)));
    });
    g.strokeStyle = MA_C[5]; g.lineWidth = 1.1; g.beginPath();
    dif.forEach(function (v, i) { i ? g.lineTo(X(i), my(v)) : g.moveTo(X(i), my(v)); });
    g.stroke();
    g.strokeStyle = '#57c8ff'; g.beginPath();
    dea.forEach(function (v, i) { i ? g.lineTo(X(i), my(v)) : g.moveTo(X(i), my(v)); });
    g.stroke();
    g.fillStyle = MUT;
    g.fillText(mhi.toFixed(1), W - padR + 4, mT + 10);
    g.fillText('-' + mhi.toFixed(1), W - padR + 4, mT + mH - 2);

    // 面板分隔線 + 日期軸(首/中/尾)
    g.fillStyle = MUT; g.font = '10px monospace';
    [0, Math.floor(n / 2), n - 1].forEach(function (i) {
      var d = rows[i][0];
      g.fillText(d.slice(5), Math.min(X(i), W - padR - 34), kH + gap - 2);
    });

    return { ma5: ma5[n - 1], ma20: ma20[n - 1], ma60: ma60[n - 1],
             v5: v5[n - 1], v20: v20[n - 1],
             dif: dif[n - 1], dea: dea[n - 1] };
  }

  function fmtN(v) {
    if (v == null) return '—';
    return v >= 100 ? v.toFixed(0) : v.toFixed(2);
  }

  function openPopup(code) {
    var mask = document.createElement('div'); mask.className = 'klx-mask';
    mask.innerHTML =
      '<div class="klx-box"><div class="klx-head"><span id="klx-t">' + code +
      ' 載入中…</span><span id="klx-chg"></span>' +
      '<button class="klx-close">✕ 關閉</button></div>' +
      '<div class="klx-leg" id="klx-l1"></div>' +
      '<canvas id="klx-cv" style="width:100%;height:min(62vh,520px);display:block"></canvas>' +
      '<div class="klx-leg" id="klx-l2"></div></div>';
    document.body.appendChild(mask);
    function close() { mask.remove(); document.removeEventListener('keydown', esc); }
    function esc(e) { if (e.key === 'Escape') close(); }
    mask.addEventListener('click', function (e) { if (e.target === mask) close(); });
    mask.querySelector('.klx-close').addEventListener('click', close);
    document.addEventListener('keydown', esc);

    fetch('/api/kline/' + code).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.rows || !d.rows.length) throw new Error(d.error || '無資料');
        var rows = d.rows;
        var last = rows[rows.length - 1], prev = rows.length > 1 ? rows[rows.length - 2] : last;
        var chg = (last[4] / prev[4] - 1) * 100;
        document.getElementById('klx-t').textContent =
          code + ' ' + (d.name || '') + '  ' + last[4];
        var chEl = document.getElementById('klx-chg');
        chEl.textContent = (chg >= 0 ? '▲+' : '▼') + chg.toFixed(2) + '%';
        chEl.style.color = chg >= 0 ? UP : DN;
        var cv = document.getElementById('klx-cv');
        var render = function () {
          var lv = draw(cv, rows);
          document.getElementById('klx-l1').innerHTML =
            '日K  <span style="color:' + MA_C[5] + '">MA5:' + fmtN(lv.ma5) + '</span>  ' +
            '<span style="color:' + MA_C[20] + '">MA20:' + fmtN(lv.ma20) + '</span>  ' +
            '<span style="color:' + MA_C[60] + '">MA60:' + fmtN(lv.ma60) + '</span>' +
            '<span style="color:#8b98a9">  (' + rows[0][0] + ' ~ ' + last[0] + ')</span>';
          document.getElementById('klx-l2').innerHTML =
            '<span style="color:#8b98a9">VOL(張) </span>' +
            '<span style="color:' + MA_C[5] + '">5T:' + Math.round(lv.v5 || 0).toLocaleString() + '</span> ' +
            '<span style="color:' + MA_C[20] + '">20T:' + Math.round(lv.v20 || 0).toLocaleString() + '</span>' +
            '<span style="color:#8b98a9">  |  MACD(12,26,9) </span>' +
            '<span style="color:' + MA_C[5] + '">DIF:' + lv.dif.toFixed(2) + '</span> ' +
            '<span style="color:#57c8ff">MACD9:' + lv.dea.toFixed(2) + '</span>';
        };
        render();
        window.addEventListener('resize', render);
      })
      .catch(function (e) {
        mask.querySelector('.klx-box').innerHTML =
          '<div class="klx-head">' + code +
          '<button class="klx-close">✕ 關閉</button></div>' +
          '<div class="klx-err">⚠ ' + e.message + '</div>';
        mask.querySelector('.klx-close').addEventListener('click', close);
      });
  }

  // 「4碼代號 + 空格 + 非數字(名稱)」才視為個股格(避開日期/價格)
  var RE = /(?:^|\s)(\d{4})\s+[^\d\s]/;
  function codeOf(el) {
    var td = el.closest ? el.closest('td') : null;
    if (!td) return null;
    var m = (td.textContent || '').match(RE);
    return m ? m[1] : null;
  }
  function boot() {
    document.querySelectorAll('td').forEach(function (td) {
      if (RE.test(td.textContent || '')) td.classList.add('klx-c');
    });
    document.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('.klx-mask')) return;
      if (e.target.closest && e.target.closest('a,button,input,select,summary')) return;
      var c = codeOf(e.target);
      if (c) openPopup(c);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else boot();
})();

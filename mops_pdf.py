"""Download MOPS financial-report PDFs + parse inventory-note breakdown.

Source: doc.twse.com.tw t57sb01 form (3-step POST sequence):
  1. GET form (warm-up)
  2. POST step=1 with co_id/year/seamon/mtype=A/dtype=AI1 → server prepares filename
  3. POST step=9 with filename → returns HTML with timestamped /pdf/...pdf URL
  4. GET that URL → PDF bytes

Cache: pdf_cache/{code}_{rocyear}Q{q}.pdf (≤ 5-8 MB each).

Inventory note parsing:
  - locate section starting with "十X、存貨" or "存 貨" header
  - regex per line: 中文 category + 3 amounts (current / prev quarter / yoy)
  - map to standardized category codes (raw / wip / semi / finished / by /
    merchandise / materials)

Standardized categories (台灣 IFRS / TIFRS 通用):
  raw_materials      原料 / 原物料
  work_in_progress   在製品
  semi_finished      半成品
  finished_goods     製成品 / 成品
  byproducts         副產品
  merchandise        商品存貨
  materials_supplies 物料及零件 / 物料
  in_transit         在途存貨

Returns multi-date data because each PDF (e.g. 25Q1) reports 3 columns:
current quarter-end, prior quarter-end, year-ago quarter-end.
"""

import os
import re
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PDF_CACHE = os.path.join(HERE, "pdf_cache")
os.makedirs(PDF_CACHE, exist_ok=True)

FORM_URL = "https://doc.twse.com.tw/server-java/t57sb01"

# Standardized category → 中文 patterns (longest first to avoid prefix collisions)
CATEGORY_PATTERNS = [
    ("merchandise", ["商品存貨", "商品"]),
    ("raw_materials", ["原物料", "原料", "材料"]),
    ("work_in_progress", ["在製品"]),
    ("semi_finished", ["半成品"]),
    ("finished_goods", ["製成品", "成品"]),
    ("byproducts", ["副產品"]),
    ("materials_supplies", ["物料及零件", "物料零件", "物料", "消耗品", "雜項"]),
    ("in_transit", ["在途存貨", "在途品", "在途"]),
    ("writedowns", ["備抵存貨跌價損失", "備抵跌價損失", "備抵損失"]),
]


def _classify(label: str) -> str:
    """Map raw 中文 category text to a standardized key."""
    clean = re.sub(r"\s+", "", label)
    for key, patterns in CATEGORY_PATTERNS:
        if any(p in clean for p in patterns):
            return key
    return f"other:{clean}"


def _make_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        ("Referer", FORM_URL),
    ]
    return opener


def download_annual_report(stock_code: str, roc_year: int,
                            force: bool = False) -> str | None:
    """Download the 年報本文 (Chinese annual-report book, mtype=F dtype=F04)
    for a company. Returns path to cached PDF or None.

    `roc_year` is the 民國 filing year (e.g. 115 = filed 2026, covers FY2025).
    F04 is the full annual-report book (~5-10 MB, 80+ pages) that contains
    the 「主要股東名單 / 持股比例占前十名之股東」 table.
    """
    cache_path = os.path.join(
        PDF_CACHE, f"{stock_code}_AR{roc_year}.pdf")
    if not force and os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
        return cache_path

    opener = _make_opener()
    try:
        opener.open(FORM_URL, timeout=15).read()
        # Step 1: list mtype=F files, pick the F04 (年報本文中文版)
        data = urllib.parse.urlencode({
            "step": "1", "colorchg": "1", "co_id": stock_code,
            "year": str(roc_year), "seamon": "", "mtype": "F",
        }).encode()
        r = opener.open(urllib.request.Request(
            FORM_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ), timeout=20)
        body = r.read().decode("big5", errors="replace")
        files = re.findall(
            r'readfile2?\("([^"]*)","([^"]*)","([^"]+\.pdf)"\)', body)
        f04 = next((fn for _, _, fn in files
                    if re.search(r"F04\.pdf$", fn)), None)
        if not f04:
            return None

        # Step 2: resolve timestamped download URL
        data = urllib.parse.urlencode({
            "step": "9", "kind": "F", "co_id": stock_code,
            "filename": f04, "DEBUG": "",
        }).encode()
        r = opener.open(urllib.request.Request(
            FORM_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ), timeout=30)
        body = r.read().decode("big5", errors="replace")
        m = re.search(r"href='(/pdf/[^']+\.pdf)'", body)
        if not m:
            return None
        pdf_url = "https://doc.twse.com.tw" + m.group(1)

        r = opener.open(pdf_url, timeout=120)
        blob = r.read()
        if not blob.startswith(b"%PDF"):
            return None
        with open(cache_path, "wb") as f:
            f.write(blob)
        return cache_path
    except Exception as ex:
        print(f"[mops_pdf] annual-report download FAILED {stock_code} "
              f"AR{roc_year}: {type(ex).__name__}: {ex}", file=sys.stderr)
        return None


def parse_major_shareholders(pdf_path: str) -> dict:
    """Parse 「主要股東名單」(top-10 shareholders) from an annual-report PDF.

    Returns:
      {
        "record_date": "YYYY-MM-DD" | None,   # 停止過戶日 (snapshot date)
        "shareholders": [{"name": str, "shares": int, "pct": float}, ...],
      }
    Shares in 股 (not 張). Empty list if the table isn't found.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber not installed: pip install pdfplumber")
    import unicodedata

    # Early-exit scan: extract text page-by-page; once the shareholders
    # heading appears, grab that page + next 2 and stop. Avoids extracting
    # all ~87 pages with pdfplumber (which is slow, ~0.3s/page).
    collected = []
    found_at = None
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            t = unicodedata.normalize("NFKC", page.extract_text() or "")
            collected.append(t)
            if found_at is None and (
                    "主要股東名單" in t or "持股比例占前十名" in t):
                found_at = i
            if found_at is not None and i >= found_at + 2:
                break
    text = "\n".join(collected)

    # The cleanest table is under "主要股東名單"; fall back to the
    # "持股比例占前十名之股東" relationship table if that heading is absent.
    seg = None
    m = re.search(r"主要股東名單(.*?)(?:股利政策|股利分派|公司股利|３、|3、)",
                  text, re.S)
    if m:
        seg = m.group(1)
    else:
        m = re.search(r"持股比例占前十名之股東(.*?)(?:公司、公司之董事|募資情形)",
                      text, re.S)
        seg = m.group(1) if m else None
    if not seg:
        return {"record_date": None, "shareholders": []}

    record_date = None
    # 停止過戶日 may sit just before the section; widen the search to the
    # section plus the preceding ~400 chars, and accept 基準日 as a synonym.
    head = text[max(0, text.find(seg[:30]) - 400):text.find(seg[:30]) + len(seg)] \
        if seg[:30] in text else seg
    rd = re.search(r"(?:停止過戶日|基準日)[:：]?\s*(?:民國)?\s*(\d+)\s*年"
                   r"\s*(\d+)\s*月\s*(\d+)\s*日", head)
    if rd:
        roc, mo, dy = map(int, rd.groups())
        record_date = f"{roc + 1911}-{mo:02d}-{dy:02d}"

    shareholders = []
    seen = set()
    for name, shares, pct in re.findall(
            r"(.+?)\s+([\d,]{4,})\s+([\d.]+)\s*%", seg):
        name = re.sub(r"\s+", "", name.strip())
        # strip leading 註/序號 noise
        name = re.sub(r"^[\d.、\(\)註]+", "", name)
        if not name or name in seen:
            continue
        seen.add(name)
        shareholders.append({
            "name": name,
            "shares": int(shares.replace(",", "")),
            "pct": float(pct),
        })
        if len(shareholders) >= 10:
            break
    return {"record_date": record_date, "shareholders": shareholders}


def fetch_major_shareholders(stock_code: str,
                             roc_year: int | None = None) -> dict:
    """Top-level: download + parse top-10 shareholders for a stock.

    Tries the current 民國 filing year first, falls back one year if the
    company hasn't filed its annual report yet. Returns:
      {"record_date", "shareholders", "data_year", "source_pdf"} or
      {"error": "..."}.
    """
    import json
    if roc_year is None:
        roc_year = datetime.now().year - 1911
    for yr in (roc_year, roc_year - 1):
        # JSON cache of the parsed result — re-parsing an 87-page PDF with
        # pdfplumber on every web request takes ~20s; cache makes it instant.
        json_cache = os.path.join(
            PDF_CACHE, f"{stock_code}_AR{yr}.shareholders.json")
        if os.path.exists(json_cache):
            try:
                with open(json_cache, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        path = download_annual_report(stock_code, yr)
        if not path:
            continue
        parsed = parse_major_shareholders(path)
        if parsed["shareholders"]:
            parsed["data_year"] = yr
            parsed["source_pdf"] = os.path.basename(path)
            try:
                with open(json_cache, "w", encoding="utf-8") as f:
                    json.dump(parsed, f, ensure_ascii=False)
            except Exception:
                pass
            return parsed
    return {"error": "找不到年報或無法解析主要股東名單",
            "shareholders": []}


def download_pdf(stock_code: str, roc_year: int, season: int,
                 force: bool = False) -> str | None:
    """Download a single (code, ROC year, season) financial-report PDF
    (IFRSs 合併財報 = mtype A / dtype AI1). Returns path to cached file,
    or None on failure.

    `roc_year` is 民國年 (e.g., 114 for 2025).
    `season` ∈ {1, 2, 3, 4}.
    """
    cache_path = os.path.join(
        PDF_CACHE, f"{stock_code}_{roc_year}Q{season}.pdf")
    if not force and os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
        return cache_path

    opener = _make_opener()
    try:
        # Step 0: warm-up
        opener.open(FORM_URL, timeout=15).read()

        # Step 1: server prepares filename
        data = urllib.parse.urlencode({
            "step": "1", "colorchg": "1",
            "co_id": stock_code, "year": str(roc_year),
            "seamon": str(season), "mtype": "A", "dtype": "AI1",
        }).encode()
        r = opener.open(urllib.request.Request(
            FORM_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ), timeout=20)
        body = r.read().decode("big5", errors="replace")
        # Some companies don't file IFRSs (financial sector, foreign), skip
        if "readfile2" not in body:
            return None

        # Filename pattern: 202501_2330_AI1.pdf (西元年+季別 + co + dtype)
        # Get directly from page to be robust against pattern changes
        m = re.search(r'readfile2\("A","[^"]+","([^"]+\.pdf)"\)', body)
        if not m:
            return None
        filename = m.group(1)

        # Step 2: request timestamped download URL
        data = urllib.parse.urlencode({
            "step": "9", "kind": "A", "co_id": stock_code,
            "filename": filename, "DEBUG": "",
        }).encode()
        r = opener.open(urllib.request.Request(
            FORM_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ), timeout=30)
        body = r.read().decode("big5", errors="replace")
        m = re.search(r"href='(/pdf/[^']+\.pdf)'", body)
        if not m:
            return None
        pdf_url = "https://doc.twse.com.tw" + m.group(1)

        # Step 3: fetch the actual PDF
        r = opener.open(pdf_url, timeout=120)
        if not r.headers.get("Content-Type", "").startswith("application/pdf"):
            return None
        blob = r.read()
        if not blob.startswith(b"%PDF"):
            return None
        with open(cache_path, "wb") as f:
            f.write(blob)
        return cache_path
    except Exception:
        return None


def parse_inventory_breakdown(pdf_path: str) -> dict:
    """Parse inventory note from a financial-report PDF.

    Returns dict:
      {
        "dates": ["YYYY-MM-DD", "YYYY-MM-DD", "YYYY-MM-DD"],
        "categories": {
          "raw_materials":      {"label": "原料",       "amounts": [a,b,c]},
          "work_in_progress":   {"label": "在製品",     "amounts": [a,b,c]},
          ...
        },
        "totals": [t1, t2, t3],
      }

    Amounts are in TWD 仟元 (千 NTD). Three columns correspond to the three
    period-end dates reported in the note (typically current quarter,
    prior quarter, year-ago quarter).
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber not installed: pip install pdfplumber")

    import unicodedata
    out = {"dates": [], "categories": {}, "totals": []}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # NFKC normalization — MOPS PDFs sometimes use CJK Compatibility
            # Ideograph variants (e.g. U+F98E for 年, U+F9BE for 料) which
            # break 中文 regexes. NFKC folds them to canonical forms.
            text = unicodedata.normalize("NFKC", text)
            # Normalize: pdfplumber sometimes renders 中文 with extra spaces
            # between chars (e.g. "製 成 品"). Strip those for keyword search
            # but keep original text for amount extraction (numbers' commas
            # depend on the exact spacing).
            text_compact = re.sub(r"(?<=[一-鿿豈-﫿])\s+(?=[一-鿿豈-﫿])", "", text)
            # pdfplumber sometimes merges the date-header line with the
            # first data row (e.g. "...年3月31日製成品 $ ...") — split.
            text_compact = re.sub(r"(\d+年\d+月\d+日)\s*([一-鿿豈-﫿])",
                                   r"\1\n\2", text_compact)
            text_compact = re.sub(
                r"(\d{2,4}[./-]\d{1,2}[./-]\d{1,2})\s*([一-鿿豈-﫿])",
                r"\1\n\2", text_compact)
            if not any(k in text_compact for k in
                       ["原料", "在製品", "製成品", "原物料", "存貨明細"]):
                continue
            # Find the section heading using compact text. MOPS reports use
            # varied numbering: "十二、存貨" / "(四)存貨" / "六、存貨" etc.
            # Try matching any of these patterns.
            # Headings vary: "十二、存貨" / "(四)存貨" / "六、存貨" / "(十二)存貨"
            # 5347 uses "十三、 存貨" (space between 、 and 存) — 、 is not in
            # CJK ideograph range so space-normalization regex doesn't catch
            # it. Allow optional whitespace after 、 / closing paren.
            heading_re = re.compile(
                r"(?:[一二三四五六七八九十]{1,3}、\s*|\([一二三四五六七八九十]{1,3}\)\s?)"
                r"[一-鿿豈-﫿]*\s?存\s?貨"
            )
            # Find ALL heading matches and pick one that actually has data
            # (date pattern within first 300 chars after heading). 年報 has
            # 存貨 mentioned in accounting policies first (no data) then in
            # notes later (with data).
            # Date patterns: "114年3月31日" / "114.3.31" / "2025/3/31" /
            # "2025-3-31". Allow ROC (2-3 digit) or Western (4 digit) year.
            date_pat = (
                r"(?:\d{2,4}年\s*\d{1,2}月\s*\d{1,2}日"
                r"|\d{2,4}[./-]\d{1,2}[./-]\d{1,2})"
            )
            m_heading = None
            for cand in heading_re.finditer(text_compact):
                tail = text_compact[cand.start():cand.start() + 400]
                # Require BOTH a date AND an inventory category keyword
                # right after the heading — rules out 存貨會計政策 sections
                has_date = re.search(date_pat, tail)
                has_cat = any(k in tail for k in
                              ["原料", "材料", "在製品", "製成品", "商品"])
                if has_date and has_cat:
                    m_heading = cand
                    break
            if not m_heading:
                m_heading = heading_re.search(text_compact)
            if m_heading:
                idx = m_heading.start()
            else:
                # Fallback: find first inventory keyword and back up
                positions = [text_compact.find(k)
                             for k in ("原料", "在製品", "製成品", "材料")
                             if text_compact.find(k) >= 0]
                if not positions:
                    continue
                idx = max(0, min(positions) - 200)
            text = text_compact  # work in the normalized version henceforth

            # Cap section at next 十N、 heading or 1500 chars
            section = text[idx:idx + 1600]
            cap = re.search(r"\n[一二三四五六七八九十]+[一二三四五六七八九十]?、",
                            section[200:])
            if cap:
                section = section[:200 + cap.start()]

            # Extract column-header dates — limited to the first line(s)
            # after the heading. Look at section[:200] only to avoid picking
            # up dates from other notes that follow the inventory table.
            # Match both 114年3月31日 (Chinese) and 114.3.31 / 2025-3-31 /
            # 2025/3/31 (numeric separator) formats.
            dates_iter = re.finditer(
                r"(?:(\d{2,4})年\s*(\d{1,2})月\s*(\d{1,2})日"
                r"|(\d{2,4})[./-](\d{1,2})[./-](\d{1,2}))",
                section[:200],
            )
            # Q4 年報 has 2 cols, Q1-Q3 季報 has 3 cols. Cap at 3.
            staged_dates = []
            seen = set()
            for m in dates_iter:
                if m.group(1):  # Chinese form
                    y, mo, d = m.group(1), m.group(2), m.group(3)
                else:           # Numeric form
                    y, mo, d = m.group(4), m.group(5), m.group(6)
                yi = int(y)
                western_year = yi + 1911 if yi < 200 else yi
                date = f"{western_year}-{int(mo):02d}-{int(d):02d}"
                if date in seen:
                    continue
                seen.add(date)
                staged_dates.append(date)
                if len(staged_dates) >= 3:
                    break

            # Number of date columns drives parsing (Q4 年報 = 2 cols, Q1-Q3
            # 季報 = 3 cols). Use staged dates from this section, not
            # whatever was carried over.
            ncols = len(staged_dates) or 3
            staged_cats: dict = {}
            staged_total: list = []
            # Build regex with ncols amount groups. Each amount: optional $,
            # optional parens for negatives, then 1+ digits with commas.
            amt = r"\$?\s*\(?\s*([\d,]+)\s*\)?"
            line_re = re.compile(
                r"^\s*([一-鿿\s]+?)\s+" + r"\s+".join([amt] * ncols)
                + r"\s*$"
            )
            for line in section.splitlines():
                m = line_re.match(line)
                if not m:
                    continue
                label = re.sub(r"\s+", "", m.group(1))
                amounts = [int(m.group(i + 2).replace(",", ""))
                           for i in range(ncols)]
                if not label or "計" in label:
                    if not staged_total:
                        staged_total = amounts
                    # 合計 marks end of inventory table; stop here to avoid
                    # picking up items from subsequent sections.
                    break
                key = _classify(label)
                if key in staged_cats:
                    existing = staged_cats[key]["amounts"]
                    staged_cats[key]["amounts"] = [
                        existing[i] + amounts[i] for i in range(ncols)]
                else:
                    staged_cats[key] = {"label": label, "amounts": amounts}
            # Commit staged → out only if we actually parsed categories
            if staged_cats:
                out["dates"] = staged_dates
                out["categories"] = staged_cats
                out["totals"] = staged_total
                break

    # If no totals parsed, compute as sum of categories
    if not out["totals"] and out["categories"]:
        first = next(iter(out["categories"].values()))
        ncols = len(first["amounts"])
        out["totals"] = [
            sum(c["amounts"][i] for c in out["categories"].values())
            for i in range(ncols)
        ]
    return out


def fetch_breakdown_series(stock_code: str, years: int = 5,
                            progress=None) -> dict:
    """Download + parse ~ N years of quarterly inventory breakdowns.

    Returns dict keyed by ISO date (period-end) with each value =
    {"label_X": amount_thousand_TWD, ...} where label_X is the
    standardized category key.

    Multiple PDFs cover overlapping dates (each Q-PDF has 3 cols), so the
    same date may be merged from up to 3 sources — we keep the latest.

    `progress`: optional callable(stage_msg) for reporting.
    """
    today_roc_year = datetime.now().year - 1911
    today_month = datetime.now().month
    if today_month >= 5:
        latest_finished_season = 1  # Q1 filed by mid-May
    elif today_month >= 8:
        latest_finished_season = 2
    elif today_month >= 11:
        latest_finished_season = 3
    else:
        latest_finished_season = 4  # prior year Q4

    # Build list of (roc_year, season) to try, newest first
    targets = []
    y = today_roc_year
    s = latest_finished_season
    needed = years * 4
    for _ in range(needed + 4):  # bit of buffer
        targets.append((y, s))
        s -= 1
        if s < 1:
            s = 4
            y -= 1
    targets = targets[:needed]

    # ── Parallel download stage (biggest cold-cache speedup) ──────────────
    # Sequential 20 PDFs took ~60-80 sec (each PDF = 4 HTTP calls × ~3 sec).
    # ThreadPool 4 workers → ~15-20 sec.
    from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
    pdf_paths = {}
    with ThreadPoolExecutor(max_workers=4) as exe:
        futures = {exe.submit(download_pdf, stock_code, y, s): (y, s)
                   for y, s in targets}
        for fut in as_completed(futures):
            y, s = futures[fut]
            if progress:
                progress(f"downloaded {y}Q{s}")
            try:
                pdf_paths[(y, s)] = fut.result()
            except Exception as ex:
                print(f"[mops_pdf] download FAILED {stock_code} {y}Q{s}: "
                      f"{type(ex).__name__}: {ex}", file=sys.stderr)
                pdf_paths[(y, s)] = None

    # ── Parallel parse stage (warm-cache speedup) ────────────────────────
    # pdfplumber is CPU-bound + GIL-bound (threads don't help: 14.7s→14.9s).
    # ProcessPool 4 workers cuts 20 PDFs from ~80s to ~30s.
    parsed_map = {}
    valid_paths = [(rs, p) for rs, p in pdf_paths.items() if p]
    if valid_paths:
        try:
            with ProcessPoolExecutor(max_workers=4) as exe:
                results = list(exe.map(parse_inventory_breakdown,
                                       [p for _, p in valid_paths]))
            for (rs, p), parsed in zip(valid_paths, results):
                parsed_map[rs] = (p, parsed)
        except Exception as ex:
            # ProcessPool 整批掛掉 (e.g. Flask reload)，落回 sequential parse
            print(f"[mops_pdf] ProcessPool FAILED {stock_code} breakdown: "
                  f"{type(ex).__name__}: {ex} — fallback sequential",
                  file=sys.stderr)
            for rs, p in valid_paths:
                if progress:
                    progress(f"parsing {rs[0]}Q{rs[1]}…")
                try:
                    parsed_map[rs] = (p, parse_inventory_breakdown(p))
                except Exception as pex:
                    print(f"[mops_pdf] parse FAILED {stock_code} "
                          f"{rs[0]}Q{rs[1]} ({p}): "
                          f"{type(pex).__name__}: {pex}", file=sys.stderr)

    series: dict[str, dict] = {}
    for roc_year, season in targets:
        item = parsed_map.get((roc_year, season))
        if not item:
            continue
        path, parsed = item
        dates = parsed.get("dates", [])
        if not dates:
            print(f"[mops_pdf] parse OK but EMPTY dates {stock_code} "
                  f"{roc_year}Q{season} ({os.path.basename(path)}) "
                  f"— PDF 結構可能異常或非標準存貨揭露",
                  file=sys.stderr)
            continue
        for col, date in enumerate(dates):
            if not date or date in series:
                continue
            entry = {"_total": parsed.get("totals", [0, 0, 0])[col]
                     if len(parsed.get("totals", [])) > col else 0,
                     "_source_pdf": os.path.basename(path)}
            for key, info in parsed.get("categories", {}).items():
                amts = info["amounts"]
                if len(amts) > col:
                    entry[key] = amts[col]
                    entry[f"{key}_label"] = info["label"]
            series[date] = entry
    sorted_dates = sorted(series.keys(), reverse=True)[:years * 4]
    return {d: series[d] for d in sorted(sorted_dates)}


def parse_contract_liabilities(pdf_path: str) -> dict:
    """Extract 合約負債 (Contract Liabilities) from a financial-report PDF.

    Some companies (e.g. 3491 昇達科, 6282 康舒, 2330 台積電) don't report
    合約負債 as a top-level balance sheet line — they bury it inside
    「其他流動負債」 (Other Current Liabilities) footnote. FinMind's
    TaiwanStockBalanceSheet only reads top-level XBRL tags, so it misses
    these. This parser reads the footnote breakdown directly.

    Returns {dates: [...], amounts: [...]}: parallel lists where
      dates[i] = ISO date string (e.g. "2026-03-31")
      amounts[i] = 合約負債 in 仟元

    PDF layout (3491 115Q1 example, page 26):
        其他流動負債
          合約負債    $6,486   $6,572   $7,750
          遞延收入    -        -        2,445
          其 他      8,944    7,726    8,797
          合計      $15,430  $14,298  $18,992
    """
    try:
        import pdfplumber
        import unicodedata
    except ImportError:
        raise RuntimeError("pdfplumber not installed: pip install pdfplumber")

    out: dict = {"dates": [], "amounts": []}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = unicodedata.normalize(
                "NFKC", page.extract_text() or "")
            if "合約負債" not in text:
                continue
            # Normalize embedded CJK spaces + split date-headers from data rows
            text_compact = re.sub(
                r"(?<=[一-鿿豈-﫿])\s+(?=[一-鿿豈-﫿])", "", text)
            text_compact = re.sub(
                r"(\d+年\d+月\d+日)\s*([一-鿿豈-﫿])",
                r"\1\n\2", text_compact)
            text_compact = re.sub(
                r"(\d{2,4}[./-]\d{1,2}[./-]\d{1,2})\s*([一-鿿豈-﫿])",
                r"\1\n\2", text_compact)
            # Locate 合約負債 row
            idx = text_compact.find("合約負債")
            if idx < 0:
                continue
            # Look 400 chars upstream for the column-date header
            up = text_compact[max(0, idx - 400): idx]
            dates_found = re.findall(
                r"(?:(\d{2,4})年\s*(\d{1,2})月\s*(\d{1,2})日"
                r"|(\d{2,4})[./-](\d{1,2})[./-](\d{1,2}))",
                up,
            )
            # Prefer the LAST 2-3 dates before 合約負債 (those are this
            # table's column headers; earlier ones are from prior sections).
            dates: list[str] = []
            seen = set()
            for m in reversed(dates_found):
                if m[0]:  # Chinese form
                    y, mo, d = m[0], m[1], m[2]
                else:
                    y, mo, d = m[3], m[4], m[5]
                yi = int(y)
                wy = yi + 1911 if yi < 200 else yi
                date = f"{wy}-{int(mo):02d}-{int(d):02d}"
                if date in seen:
                    continue
                seen.add(date)
                dates.append(date)
                if len(dates) >= 3:
                    break
            dates.reverse()  # restore chronological order in column sense
            if not dates:
                continue
            ncols = len(dates)

            # Parse the 合約負債 row — capture amounts
            line_end = text_compact.find("\n", idx)
            if line_end < 0:
                line_end = idx + 200
            line = text_compact[idx:line_end]
            # Pattern: "合約負債 $ N1 $ N2 $ N3"  OR with dash for missing
            amt = r"(?:\$?\s*\(?\s*([\d,]+|[-—－])\s*\)?)"
            line_re = re.compile(
                r"^合約負債\s+" + r"\s+".join([amt] * ncols)
            )
            m = line_re.match(line)
            if not m:
                # Try with looser separator (in case of weird spacing)
                m = re.match(
                    r"^合約負債(.+)$", line)
                if m:
                    # Extract all number-like tokens from the tail
                    tail = m.group(1)
                    nums = re.findall(r"([\d,]+|[-—－])", tail)
                    if len(nums) >= ncols:
                        nums = nums[:ncols]
                    else:
                        continue
                else:
                    continue
            else:
                nums = [m.group(i + 1) for i in range(ncols)]
            amounts: list = []
            for n in nums:
                if n in ("-", "—", "－"):
                    amounts.append(None)
                else:
                    try:
                        amounts.append(int(n.replace(",", "")))
                    except ValueError:
                        amounts.append(None)
            out["dates"] = dates
            out["amounts"] = amounts
            return out
    return out


def fetch_contract_liabilities_series(stock_code: str, years: int = 3,
                                       progress=None) -> dict:
    """Download + parse ~N years of quarterly 合約負債 from MOPS PDFs.

    Returns dict {date: amount_thousand_TWD}. Use as fallback when FinMind
    TaiwanStockBalanceSheet returns no 'CurrentContractLiabilities' row.
    """
    today_roc_year = datetime.now().year - 1911
    today_month = datetime.now().month
    if today_month >= 5:
        latest_finished_season = 1
    elif today_month >= 8:
        latest_finished_season = 2
    elif today_month >= 11:
        latest_finished_season = 3
    else:
        latest_finished_season = 4

    targets = []
    y = today_roc_year
    s = latest_finished_season
    needed = years * 4
    for _ in range(needed + 4):
        targets.append((y, s))
        s -= 1
        if s < 1:
            s = 4
            y -= 1
    targets = targets[:needed]

    # Parallel download + parse (same pattern as fetch_breakdown_series)
    from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
    pdf_paths = {}
    with ThreadPoolExecutor(max_workers=4) as exe:
        futures = {exe.submit(download_pdf, stock_code, y, s): (y, s)
                   for y, s in targets}
        for fut in as_completed(futures):
            y, s = futures[fut]
            if progress:
                progress(f"downloaded {y}Q{s}")
            try:
                pdf_paths[(y, s)] = fut.result()
            except Exception as ex:
                print(f"[mops_pdf] download FAILED {stock_code} {y}Q{s}: "
                      f"{type(ex).__name__}: {ex}", file=sys.stderr)
                pdf_paths[(y, s)] = None

    parsed_map = {}
    valid_paths = [(rs, p) for rs, p in pdf_paths.items() if p]
    if valid_paths:
        try:
            with ProcessPoolExecutor(max_workers=4) as exe:
                results = list(exe.map(parse_contract_liabilities,
                                       [p for _, p in valid_paths]))
            for (rs, _), parsed in zip(valid_paths, results):
                parsed_map[rs] = parsed
        except Exception as ex:
            print(f"[mops_pdf] ProcessPool FAILED {stock_code} "
                  f"contract_liabilities: {type(ex).__name__}: {ex} — "
                  f"fallback sequential", file=sys.stderr)
            for rs, p in valid_paths:
                try:
                    parsed_map[rs] = parse_contract_liabilities(p)
                except Exception as pex:
                    print(f"[mops_pdf] parse FAILED {stock_code} "
                          f"{rs[0]}Q{rs[1]} ({p}): "
                          f"{type(pex).__name__}: {pex}", file=sys.stderr)

    series: dict[str, int] = {}
    for roc_year, season in targets:
        parsed = parsed_map.get((roc_year, season))
        if not parsed:
            continue
        for date, amt in zip(parsed.get("dates", []),
                              parsed.get("amounts", [])):
            if date and amt is not None and date not in series:
                series[date] = amt
    sorted_dates = sorted(series.keys(), reverse=True)[:years * 4]
    return {d: series[d] for d in sorted(sorted_dates)}


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "2330"
    yrs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    print(f"Fetching {yrs}y for {code}...")
    s = fetch_breakdown_series(code, years=yrs,
                                progress=lambda m: print(f"  {m}"))
    for date in sorted(s.keys()):
        e = s[date]
        cats = [(k, v) for k, v in e.items()
                if not k.startswith("_") and not k.endswith("_label")]
        cats.sort(key=lambda kv: -kv[1])
        print(f"\n{date}  total {e.get('_total', 0):,}")
        for k, v in cats:
            lbl = e.get(f"{k}_label", k)
            pct = v / e["_total"] * 100 if e.get("_total") else 0
            print(f"  {lbl:14s} ({k:25s})  {v:>15,}  {pct:5.1f}%")

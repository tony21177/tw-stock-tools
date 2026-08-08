#!/usr/bin/env python3
"""
事件交易資料層 — TWSE/TPEx 重大訊息 + 內部人設質 + 鉅額,抓取・快取・分類。

資料源(官方 OpenAPI,免認證,實測 2026-08-08):
  上市重訊  https://openapi.twse.com.tw/v1/opendata/t187ap04_L
  上櫃重訊  https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O
  內部人+設質 https://openapi.twse.com.tw/v1/opendata/t187ap11_L (月頻 2.7 萬筆)
  鉅額交易  https://openapi.twse.com.tw/v1/exchangeReport/BFIAUU (當日)

⚠ OpenAPI 只回「近期快照」(非歷史區間)→ 每日抓當日快照存月檔累積,
   自建歷史事件庫。重訊主旨無日期區間查詢,以 announce_date 去重累積。

分類器:把重訊主旨分成事件類型。關鍵陷阱(見 docs/strategies/event-driven.md):
  - 「合併」大量命中「合併財務報告」→ 排除
  - 「取得」含「取得不動產/設備」→ 只留取得股權
快取:concept_momentum/cache/events/{material_YYYYMM|insider_YYYYMM}.json
"""

import glob
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "concept_momentum", "cache", "events")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

MATERIAL_SII = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
MATERIAL_OTC = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"
INSIDER_SII = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
# 內部人「事前申報轉讓」(法定轉讓前 3 日申報;Layer 0 提前信號)
INSIDER_XFER_SII = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"
INSIDER_XFER_OTC = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O"
BLOCK_TRADE = "https://openapi.twse.com.tw/v1/exchangeReport/BFIAUU"


# ── 分類器 ─────────────────────────────────────────────────────
def classify(subject: str) -> str:
    """重訊主旨 → 事件類型代碼。無法歸類回 'other'。"""
    s = (subject or "").replace("\n", "").replace(" ", "")

    # 公開收購(法定提前 5 日,最高優先)
    if "公開收購" in s:
        return "tender_offer"

    # 取得股權(策略投資)— 排除不動產/設備/使用權
    if "取得" in s and re.search(r"(股份|普通股|股票|特別股|可轉換公司債)", s):
        if not re.search(r"(不動產|土地|廠房|廠辦|辦公|設備|機器|使用權資產)", s):
            return "strategic_buy"

    # 併購(真 M&A)— 排除「合併財務報告/報表/iXBRL」
    if re.search(r"(合併|概括讓與|股份轉換|分割)", s) and \
            not re.search(r"(財務報告|財報|報表|iXBRL|預計召開)", s):
        return "merger"

    # 庫藏股買回
    if ("買回" in s and "股份" in s) or "庫藏" in s:
        return "treasury"

    # 減資
    if "減資" in s:
        return "capital_reduction"

    # 現金增資 / 私募 / GDR / CB
    if re.search(r"(現金增資|私募|海外存託|存託憑證|發行.{0,4}新股|可轉換公司債|轉換公司債|附認股權)", s):
        return "capital_increase"

    # 重大契約 / 合資 / 大單
    if re.search(r"(簽訂|合資|合作備忘錄|備忘錄|MOU|承攬|得標|重大.{0,3}(合約|契約|訂單)|供應.{0,3}協議)", s):
        return "major_contract"

    # 高層異動(排除競業禁止之類雜訊)
    if re.search(r"(總經理|董事長|財務長|發言人|經理人|執行長)", s) and \
            re.search(r"(異動|辭|解任|新任|改派|變更|補選)", s) and \
            "競業禁止" not in s:
        return "mgmt_change"

    # 訴訟 / 意外 / 裁罰
    if re.search(r"(訴訟|假處分|裁罰|處分書|火災|災害|停工|意外|工安|和解|求償)", s):
        return "litigation"

    # 更名
    if "更名" in s or "名稱由" in s:
        return "name_change"

    return "other"


EVENT_LABELS = {
    "tender_offer": "🎯 公開收購",
    "strategic_buy": "🤝 取得股權/策略投資",
    "merger": "🔗 併購/合併",
    "treasury": "💰 庫藏股買回",
    "capital_reduction": "✂ 減資",
    "capital_increase": "📈 現增/私募/CB",
    "major_contract": "📝 重大契約/大單",
    "mgmt_change": "👤 高層異動",
    "litigation": "⚖ 訴訟/意外",
    "name_change": "🔤 更名",
    "other": "…其他",
}


# ── 抓取 ───────────────────────────────────────────────────────
def _get_json(url, retries=2):
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=25) as r:
                return json.loads(r.read())
        except Exception:
            if i < retries:
                time.sleep(3)
    return []


def _roc_date(s: str) -> str:
    """'1150807' 或 '115/08/07' → '20260807'。"""
    s = str(s).strip().replace("/", "")
    m = re.match(r"(\d{3})(\d{2})(\d{2})$", s)
    if m:
        return f"{int(m.group(1))+1911}{m.group(2)}{m.group(3)}"
    return s


def fetch_material() -> list[dict]:
    """上市+上櫃重訊,統一 schema + 分類。"""
    out = []
    for market, url, code_k, name_k in [
            ("sii", MATERIAL_SII, "公司代號", "公司名稱"),
            ("otc", MATERIAL_OTC, "SecuritiesCompanyCode", "CompanyName")]:
        for r in _get_json(url):
            subj = r.get("主旨 ") or r.get("主旨") or ""
            code = r.get(code_k, "").strip()
            if not code:
                continue
            ad = _roc_date(r.get("發言日期") or r.get("出表日期") or "")
            out.append({
                "code": code, "name": r.get(name_k, "").strip(),
                "market": market, "date": ad,
                "time": (r.get("發言時間") or "").strip(),
                "subject": subj.replace("\n", " ").strip(),
                "type": classify(subj),
            })
    return out


def fetch_insider() -> list[dict]:
    """內部人持股+設質(月頻)。回傳設質比例高或有異動者。"""
    out = []
    for r in _get_json(INSIDER_SII):
        code = r.get("公司代號", "").strip()
        if not (len(code) == 4 and code.isdigit()):
            continue
        try:
            hold = int(str(r.get("目前持股", "0")).replace(",", "") or 0)
            pledge = int(str(r.get("設質股數", "0")).replace(",", "") or 0)
        except ValueError:
            hold = pledge = 0
        pr = pledge / hold * 100 if hold > 0 else 0
        out.append({
            "code": code, "name": r.get("公司名稱", "").strip(),
            "title": r.get("職稱", "").strip(), "person": r.get("姓名", "").strip(),
            "month": _roc_date(str(r.get("資料年月", "")) + "01")[:6],
            "hold": hold, "pledge": pledge, "pledge_ratio": round(pr, 1),
        })
    return out


def fetch_insider_transfer() -> list[dict]:
    """內部人事前申報轉讓(上市+上櫃)。董監/大股東轉讓前 3 日申報,
    含轉讓方式、股數、有效期間 —— 屬 Layer 0 提前信號。"""
    out = []
    for market, url in [("sii", INSIDER_XFER_SII), ("otc", INSIDER_XFER_OTC)]:
        for r in _get_json(url):
            code = (r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
            if not (len(code) == 4 and code.isdigit()):
                continue
            try:
                sh = int(str(r.get("預定轉讓方式及股數-轉讓股數", "0")).replace(",", "") or 0)
            except ValueError:
                sh = 0
            out.append({
                "code": code, "name": r.get("公司名稱", "").strip(),
                "market": market,
                "date": _roc_date(r.get("出表日期", "")),
                "who": r.get("申報人身分", "").strip(),
                "person": r.get("姓名", "").strip(),
                "method": r.get("預定轉讓方式及股數-轉讓方式", "").strip(),
                "shares": sh,
                "receiver": r.get("受讓人", "").strip(),
                "period": r.get("有效轉讓期間", "").strip(),
            })
    out.sort(key=lambda x: -x["shares"])
    return out


def update_daily(force: bool = False) -> dict:
    """抓當日重訊 + 內部人月檔,存月檔累積(去重)。"""
    from datetime import datetime
    os.makedirs(CACHE_DIR, exist_ok=True)
    yyyymm = datetime.now().strftime("%Y%m")
    stats = {}

    # 重訊:累積去重(key = code+date+subject)
    mpath = os.path.join(CACHE_DIR, f"material_{yyyymm}.json")
    existing = json.load(open(mpath)) if os.path.exists(mpath) else []
    seen = {(e["code"], e["date"], e["subject"]) for e in existing}
    new = [e for e in fetch_material()
           if (e["code"], e["date"], e["subject"]) not in seen]
    existing.extend(new)
    json.dump(existing, open(mpath, "w"), ensure_ascii=False)
    stats["material_new"] = len(new)
    stats["material_total"] = len(existing)

    # 內部人:月檔覆寫(月頻快照)
    ipath = os.path.join(CACHE_DIR, f"insider_{yyyymm}.json")
    if force or not os.path.exists(ipath):
        ins = fetch_insider()
        json.dump(ins, open(ipath, "w"), ensure_ascii=False)
        stats["insider"] = len(ins)
    else:
        stats["insider"] = "skip"

    # 事前申報轉讓:每日累積去重(短期有效,存月檔)
    xpath = os.path.join(CACHE_DIR, f"xfer_{yyyymm}.json")
    xexist = json.load(open(xpath)) if os.path.exists(xpath) else []
    xseen = {(e["code"], e["date"], e["person"], e["shares"]) for e in xexist}
    xnew = [e for e in fetch_insider_transfer()
            if (e["code"], e["date"], e["person"], e["shares"]) not in xseen]
    xexist.extend(xnew)
    json.dump(xexist, open(xpath, "w"), ensure_ascii=False)
    stats["xfer_new"] = len(xnew)
    return stats


def load_material(months: int = 3) -> list[dict]:
    """讀近 N 月重訊月檔合併,依日期降冪。"""
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "material_*.json")))[-months:]
    out = []
    for f in files:
        out.extend(json.load(open(f)))
    out.sort(key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)
    return out


def load_insider() -> list[dict]:
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "insider_*.json")))
    return json.load(open(files[-1])) if files else []


def load_xfer(months: int = 2) -> list[dict]:
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "xfer_*.json")))[-months:]
    out = []
    for f in files:
        out.extend(json.load(open(f)))
    out.sort(key=lambda e: (e.get("date", ""), e.get("shares", 0)), reverse=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--show", help="只印某事件類型的當日事件")
    a = ap.parse_args()
    if a.show:
        for e in fetch_material():
            if e["type"] == a.show:
                print(e["code"], e["name"], "|", e["subject"][:60])
    else:
        print(update_daily(force=a.force))

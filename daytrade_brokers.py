#!/usr/bin/env python3
"""隔日沖/短線大戶分點註冊表 — 種子 + 多來源網路交叉比對 + 資料驅動偵測.

在籌碼敘事對這些分點打 ⚡隔日沖 額外標籤（不改 外資/內資/散戶 分類），
避免把它們的買盤誤讀成內資機構認同。

⚠ 標記只描述分點慣性、非買賣訊號；data 偵測門檻先驗未回測。
"""
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "concept_momentum", "cache",
                        "daytrade_brokers.json")
BSR_DIR = os.path.join(HERE, "bsr_cache")

# 公認隔日沖分點種子（web 交叉驗證：股感、豐雲學堂、玩股網、CMoney，
# 2026-07 查證）。key = 正規化名稱，codes = 已知分點代號（可空）。
_SEED = {
    "凱基松山": ["9268"],
    "凱基城中": ["9227"],
    "凱基信義": ["9216"],
    "凱基台北": ["9200"],
    "美林": ["1440"],
    "摩根大通": ["8440"],
    "國票敦北": [],
    "富國建邦": [],
    "元大土城永寧": [],
    "統一士林": [],
    "群益金鼎大安": [],
    "中信忠孝": [],
}

# data 偵測門檻（先驗、未回測）
DT_BUY_PCT = 0.05          # 日N 淨買 ≥ 該股當日總量 5% = 大買
DT_DUMP_RATIO = 0.6       # 日N+1 賣掉 ≥ 日N 買量 60% = 隔日倒
DT_MIN_BIGBUYS = 5        # 至少 5 次大買事件才算分（樣本足夠）
# data_score = 隔日倒 / 大買事件 = 該分點「大買後隔日就倒」的比例
DT_SCORE_CONFIRM = 0.50   # ≥ 50% 大買隔日倒 = confirmed 隔日沖
DT_SCORE_CANDIDATE = 0.30  # ≥ 30% = candidate


def normalize(name: str) -> str:
    """分點名稱正規化：去空白/全形空白/連字號。"""
    return (name or "").replace(" ", "").replace("　", "").replace("-", "")


def _empty_registry() -> dict:
    return {"updated": "", "brokers": {}}


def load_registry() -> dict:
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _empty_registry()


def _save_registry(reg: dict) -> None:
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REGISTRY)


def is_daytrade(name_or_code: str, reg: dict | None = None) -> bool:
    return daytrade_info(name_or_code, reg) is not None


def daytrade_info(name_or_code: str, reg: dict | None = None) -> dict | None:
    """回該分點的註冊資訊（含 confidence），無則 None。名稱與代號雙軌。"""
    reg = reg if reg is not None else load_registry()
    brokers = reg.get("brokers", {})
    n = normalize(name_or_code)
    if n in brokers:
        return brokers[n]
    # 代號比對 + 名稱包含（種子名稱是關鍵字，實際分點名可能更長）
    for key, info in brokers.items():
        if name_or_code in (info.get("codes") or []):
            return info
        if key and key in n:
            return info
    return None


def _confidence(web_count: int, data_score: float, is_seed: bool) -> str:
    if is_seed or web_count >= 2 or data_score >= DT_SCORE_CONFIRM:
        return "confirmed"
    if web_count >= 1 or data_score >= DT_SCORE_CANDIDATE:
        return "candidate"
    return "candidate"


def merge_registry(seed: dict, web: dict | None, data: dict | None,
                   today: str) -> dict:
    """三來源併 → 註冊表。
    seed = {name: [codes]}；web = {name: {"web_count": n, "codes": [...]}}；
    data = {name: {"data_score": f, "codes": [...]}}。
    """
    web = web or {}
    data = data or {}
    names = set(map(normalize, seed)) | set(map(normalize, web)) \
        | set(map(normalize, data))
    prev = load_registry().get("brokers", {})
    out = {}
    for n in names:
        # 找各來源的原始 key（正規化後對應）
        seed_codes = next((v for k, v in seed.items()
                           if normalize(k) == n), None)
        web_e = next((v for k, v in web.items() if normalize(k) == n), None)
        data_e = next((v for k, v in data.items() if normalize(k) == n), None)
        is_seed = seed_codes is not None
        web_count = (web_e or {}).get("web_count", 0)
        data_score = round((data_e or {}).get("data_score", 0.0), 3)
        sources = []
        if is_seed:
            sources.append("seed")
        if web_count:
            sources.append("web")
        if data_score:
            sources.append("data")
        codes = sorted(set((seed_codes or [])
                           + ((web_e or {}).get("codes") or [])
                           + ((data_e or {}).get("codes") or [])))
        out[n] = {
            "sources": sources, "web_count": web_count,
            "data_score": data_score,
            "confidence": _confidence(web_count, data_score, is_seed),
            "codes": codes,
            "first_seen": prev.get(n, {}).get("first_seen", today),
            "last_updated": today,
        }
    return {"updated": today, "brokers": out}


# ── 資料驅動偵測 ────────────────────────────────────────────────
def _load_day_nets(path: str) -> tuple[dict[str, dict], int] | None:
    """讀一日 BSR → ({code: {name, net, buy, sell}}, 當日總量)。

    優先 plain `{code}_{date}.json`（brokers dict，小 15 倍）；只有
    prices 檔時 fallback 解析 rows。回 None 表示讀取失敗/空。
    """
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    agg: dict[str, dict] = {}
    if "brokers" in d:                          # plain 檔
        for bid, b in d["brokers"].items():
            buy, sell = b.get("buy", 0), b.get("sell", 0)
            agg[bid] = {"name": (b.get("name", "").replace(" ", "")),
                        "buy": buy, "sell": sell, "net": buy - sell}
        total = d.get("total_buy") or sum(a["buy"] for a in agg.values())
    else:                                        # prices 檔 rows
        for r in d.get("rows", []):
            a = agg.setdefault(r["broker_id"], {
                "name": r["broker_name"].replace(" ", ""), "buy": 0,
                "sell": 0})
            a["buy"] += r["buy"]
            a["sell"] += r["sell"]
        for a in agg.values():
            a["net"] = a["buy"] - a["sell"]
        total = sum(a["buy"] for a in agg.values())
    return (agg, total) if agg else None


def detect_from_data(bsr_dir: str | None = None, days: int = 50) -> dict:
    """掃 bsr_cache → 每個分點的隔日沖分數。

    對每個 (股票, 連續兩交易日) 配對：日N 淨買 ≥ 當日總量 DT_BUY_PCT
    且 日N+1 淨賣、賣量 ≥ 日N 淨買 × DT_DUMP_RATIO → 一次 cycle。
    分數 = cycle 數 / 該分點出現天數（正規化活躍度），≥ DT_MIN_CYCLES 才計。
    優先讀 plain 檔（小），無則 prices。
    回 {正規化名: {"data_score": f, "codes": [...], "cycles": n}}。
    """
    bsr_dir = bsr_dir or BSR_DIR
    # 依股票分組：同 (code,date) 若 plain+prices 都在，優先 plain
    by_stock_date: dict[tuple, str] = {}
    for f in glob.glob(os.path.join(bsr_dir, "*.json")):
        base = os.path.basename(f)
        is_prices = base.endswith("_prices.json")
        stem = base.replace("_prices.json", "").replace(".json", "")
        parts = stem.split("_")
        if len(parts) != 2 or len(parts[1]) != 8:
            continue
        key = (parts[0], parts[1])
        # plain 優先：prices 只在 plain 不存在時採用
        if key not in by_stock_date or not is_prices:
            by_stock_date[key] = f
    by_stock: dict[str, list[str]] = defaultdict(list)
    for (code, _date), f in by_stock_date.items():
        by_stock[code].append(f)

    cycles: dict[str, int] = defaultdict(int)     # code -> 隔日倒次數
    big_buys: dict[str, int] = defaultdict(int)   # code -> 大買事件數
    names: dict[str, str] = {}

    n_stocks = len(by_stock)
    for si, (stock, files) in enumerate(by_stock.items()):
        if si and si % 50 == 0:
            print(f"[daytrade] 掃描 {si}/{n_stocks} 檔股票…",
                  file=sys.stderr, flush=True)
        # 依日期排序（檔名含 YYYYMMDD）
        files.sort(key=lambda p: os.path.basename(p).split("_")[1][:8])
        files = files[-days:]
        prev_agg = prev_total = None
        for f in files:
            res = _load_day_nets(f)
            if not res:
                prev_agg = prev_total = None
                continue
            agg, total_vol = res
            for code, a in agg.items():
                names[code] = a["name"]
            if prev_agg and prev_total and prev_total > 0:
                for code, p in prev_agg.items():
                    # 日N(prev) 是否大買事件
                    if p["net"] < DT_BUY_PCT * prev_total:
                        continue
                    big_buys[code] += 1
                    a = agg.get(code)
                    # 日N+1(today) 是否隔日倒
                    if (a and a["net"] < 0
                            and a["sell"] >= DT_DUMP_RATIO * p["net"]):
                        cycles[code] += 1
            prev_agg, prev_total = agg, total_vol

    out: dict[str, dict] = {}
    for code, nb in big_buys.items():
        if nb < DT_MIN_BIGBUYS:
            continue
        cyc = cycles.get(code, 0)
        score = cyc / nb                          # 大買後隔日倒的比例
        if score < DT_SCORE_CANDIDATE:
            continue                              # 低於候選門檻不收
        nm = normalize(names.get(code, code))
        if not nm:
            continue
        e = out.setdefault(nm, {"data_score": 0.0, "codes": [],
                                "cycles": 0, "big_buys": 0})
        if score > e["data_score"]:
            e["data_score"] = round(score, 3)
        e["cycles"] += cyc
        e["big_buys"] += nb
        if code not in e["codes"]:
            e["codes"].append(code)
    return out


_WEB_PROMPT = """你是台股籌碼研究員。請上網搜尋「台股隔日沖分點名單 / 隔日沖大戶券商」，
**至少查 3 個獨立來源**（例如 股感 StockFeel、玩股網 wantgoo、CMoney、永豐豐雲學堂、
財經部落格、Yahoo 股市等），把各家列出的「隔日沖 / 當沖大戶」券商分點整理出來。

規則：
- 對每個分點，記錄它出現在**幾個獨立來源**（同一網站不同頁算一個來源）
- 分點名稱用「券商簡稱+分行」格式（如 凱基松山、國票敦北），有券商代號就附上
- 只收「隔日沖 / 短線大戶」性質的分點，不要一般法人/自營
- 排除純外資（美林、摩根大通這類雖也隔日沖，但另有身分，可收但標註）

最後**只輸出一段 JSON**（不要其他文字、不要 markdown code fence），格式：
{"brokers": [{"name": "凱基松山", "codes": ["9268"], "source_count": 3,
              "sources": ["股感","玩股網","豐雲學堂"]}, ...]}
source_count = 出現的獨立來源數。查不到就回 {"brokers": []}。"""


def update_from_web(write: bool = True, timeout: int = 900) -> dict | None:
    """派 headless Claude 多來源搜尋隔日沖名單 → 交叉比對 → merge。

    回 merged registry，或 None（claude 失敗）。≥2 來源 = confirmed。
    """
    import shutil
    import subprocess
    claude = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not os.path.exists(claude):
        print("[WARN] claude CLI 不存在", file=sys.stderr)
        return None
    try:
        proc = subprocess.run(
            [claude, "-p", "--output-format", "text",
             "--dangerously-skip-permissions"],
            input=_WEB_PROMPT, capture_output=True, text=True,
            timeout=timeout, cwd=HERE)
    except Exception as e:
        print(f"[WARN] claude 執行失敗: {e}", file=sys.stderr)
        return None
    out = (proc.stdout or "").strip()
    # 容錯：抽出第一段 {...}
    import re
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        print(f"[WARN] claude 回傳無 JSON: {out[:200]}", file=sys.stderr)
        return None
    try:
        parsed = json.loads(m.group(0))
    except Exception as e:
        print(f"[WARN] JSON parse 失敗: {e}", file=sys.stderr)
        return None
    web = {}
    for b in parsed.get("brokers", []):
        nm = b.get("name", "")
        if not nm:
            continue
        web[nm] = {"web_count": int(b.get("source_count", 1) or 1),
                   "codes": b.get("codes", []) or []}
    if not web:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    # 沿用現有 data 分數
    prev = load_registry().get("brokers", {})
    data = {k: {"data_score": v.get("data_score", 0.0),
                "codes": v.get("codes", [])}
            for k, v in prev.items() if v.get("data_score")}
    reg = merge_registry(_SEED, web, data, today)
    if write:
        _save_registry(reg)
    return reg


def update_from_data(bsr_dir: str | None = None, days: int = 50,
                     write: bool = True) -> dict:
    """跑 data 偵測 → merge 進註冊表（保留現有 web）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    data = detect_from_data(bsr_dir, days)
    # 現有 web 資訊沿用
    prev = load_registry().get("brokers", {})
    web = {k: {"web_count": v.get("web_count", 0), "codes": v.get("codes", [])}
           for k, v in prev.items() if v.get("web_count")}
    reg = merge_registry(_SEED, web, data, today)
    if write:
        _save_registry(reg)
    return reg


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="store_true", help="跑資料驅動偵測")
    ap.add_argument("--days", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="印目前註冊表")
    ap.add_argument("--web", action="store_true", help="多來源網路更新")
    ap.add_argument("--weekly", action="store_true",
                    help="週更: data 偵測 + 網路交叉比對(cron 用)")
    args = ap.parse_args()
    if args.weekly:
        print("[daytrade] 週更: 資料驅動偵測…", file=sys.stderr)
        update_from_data(days=args.days, write=True)
        print("[daytrade] 週更: 多來源網路交叉比對…", file=sys.stderr)
        r = update_from_web(write=True)
        print(f"[daytrade] 網路更新 {'成功' if r else '失敗(保留現有)'}",
              file=sys.stderr)
        reg = load_registry()
        conf = sum(1 for v in reg["brokers"].values()
                   if v["confidence"] == "confirmed")
        print(f"[daytrade] 註冊表 {len(reg['brokers'])} 分點 "
              f"({conf} confirmed)", file=sys.stderr)
    elif args.web:
        r = update_from_web(write=not args.dry_run)
        print("網路更新:", "成功" if r else "失敗")
    elif args.list:
        reg = load_registry()
        for n, info in sorted(reg.get("brokers", {}).items(),
                              key=lambda x: -x[1]["data_score"]):
            print(f"{n:<16} {info['confidence']:<10} "
                  f"web{info['web_count']} data{info['data_score']} "
                  f"{'/'.join(info['sources'])} {info['codes']}")
    elif args.data:
        reg = update_from_data(days=args.days, write=not args.dry_run)
        dt = [(n, i) for n, i in reg["brokers"].items() if "data" in i["sources"]]
        print(f"data 偵測命中 {len(dt)} 分點:")
        for n, i in sorted(dt, key=lambda x: -x[1]["data_score"]):
            print(f"  {n} score={i['data_score']} {i['confidence']} {i['codes']}")

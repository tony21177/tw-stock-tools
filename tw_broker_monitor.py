#!/usr/bin/env python3
"""
分點籌碼每日掃描 + 推送

每天傍晚跑一次：
1. 抓今日全市場融資餘額快照（OpenAPI）
2. 取「今日融資餘額增加最多」的 Top N 檔
3. 每檔抓 BSR 並存 cache（CAPTCHA 用 ddddocr 解）
4. 用累積的 5 日歷史跑連動分析（前幾天會說資料不足，第 5 天起完整）
5. 依「相關係數 + 買超天數」排出 Top 10 推 Telegram

第一週累積期：每天會推「分點 BSR 已蒐集 X 檔」訊息
第 5 天起：每天推 Top 10「疑似用融資短線的分點」清單
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

from bsr_scraper import fetch_and_cache, load_history
from tw_margin_monitor import fetch_twse_today_margin, fetch_tpex_today_margin, fetch_finmind_history
from tw_broker_lookup import analyze, format_report
try:
    from stock_names import get_name as _zh_name
except ImportError:
    def _zh_name(c, fb=""):
        return fb or c

DEFAULT_CHAT_ID = "-5229750819"
TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API.format(token=bot_token)
    max_len = 4000
    chunks = [message] if len(message) <= max_len else []
    if not chunks:
        cur, lines = "", message.split("\n")
        for line in lines:
            if len(cur) + len(line) + 1 > max_len:
                chunks.append(cur); cur = line
            else:
                cur = cur + "\n" + line if cur else line
        if cur: chunks.append(cur)

    ok = True
    for i, text in enumerate(chunks):
        payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if not json.loads(resp.read().decode()).get("ok"):
                    ok = False
        except Exception as e:
            print(f"[ERROR] Telegram: {e}", file=sys.stderr)
            ok = False
        if i < len(chunks) - 1:
            time.sleep(0.5)
    return ok


def get_top_margin_increase_stocks(top_n: int = 100) -> list[tuple[str, int, int]]:
    """Returns [(stock_code, balance_today, increase)] sorted by increase desc.
    Only 4-digit numeric codes (excludes ETF / 槓桿反向 ETF / 權證 / REITs)."""
    import re
    twse = fetch_twse_today_margin()
    time.sleep(0.5)
    tpex = fetch_tpex_today_margin()
    today_data = {**twse}
    for c, info in tpex.items():
        if c not in today_data:
            today_data[c] = info

    # Filter to 4-digit numeric codes only (普通股)
    items = [(code, info["balance"], 0)
             for code, info in today_data.items()
             if info["balance"] > 1000 and re.fullmatch(r"\d{4}", code)]
    items.sort(key=lambda x: -x[1])
    return items[:top_n]


def get_strong_concept_stocks(min_score: float = 70.0) -> list[str]:
    """Read latest concept_momentum analysis result, return unique stocks
    in concepts whose sustainability_score >= min_score.

    If no fresh result file (today's), falls back to concepts.json members
    of concepts that scored ≥70 in the most recent saved result.
    Returns [] silently if neither is available.
    """
    cm_dir = os.path.join(HERE, "concept_momentum", "cache")
    results_dir = os.path.join(cm_dir, "results")
    if not os.path.isdir(results_dir):
        return []

    files = sorted([f for f in os.listdir(results_dir) if f.startswith("analysis_")])
    if not files:
        return []

    latest = os.path.join(results_dir, files[-1])
    try:
        with open(latest) as f:
            results = json.load(f)
    except Exception:
        return []

    strong_themes = [r["theme_key"] for r in results
                     if r.get("sustainability_score", 0) >= min_score]
    if not strong_themes:
        return []

    concepts_path = os.path.join(cm_dir, "concepts.json")
    try:
        with open(concepts_path) as f:
            concepts = json.load(f)
    except Exception:
        return []

    codes = set()
    for tk in strong_themes:
        for code in concepts.get("themes", {}).get(tk, {}).get("stocks", []):
            codes.add(code)
    return sorted(codes)


def scan_and_save(stock_codes: list[str], delay: float = 0.6) -> dict:
    """Fetch BSR for each stock, save to cache. Returns summary."""
    success, failed = 0, []
    for i, code in enumerate(stock_codes):
        data = fetch_and_cache(code)
        if data:
            success += 1
        else:
            failed.append(code)
        time.sleep(delay)
        if (i + 1) % 20 == 0:
            print(f"  進度 {i+1}/{len(stock_codes)} 成功 {success}", file=sys.stderr)
    return {"success": success, "failed": failed}


def analyze_all(stock_codes: list[str], days: int, finmind_token: str,
                min_corr: float = 0.5, min_days: int = 3,
                require_margin_increase: bool = True) -> list[dict]:
    """Run analyze() for each stock. Skip if insufficient history.

    require_margin_increase=True (預設): 只保留期間融資餘額為正成長的標的，
    符合「主力建倉 = 融資同步累積」原意。設 False 可看全部 (含融資退場)。"""
    all_results = []
    for i, code in enumerate(stock_codes):
        try:
            r = analyze(code, days, finmind_token,
                        min_active_days=min_days, min_correlation=min_corr,
                        top_n=5)
            if "error" not in r and r.get("candidates"):
                margin_inc = r["margin_total_increase"]
                if require_margin_increase and margin_inc <= 0:
                    continue  # 融資沒成長 = 不符合主力建倉訊號
                all_results.append({
                    "code": code,
                    "name": _zh_name(code),
                    "current_balance": r["current_balance"],
                    "margin_increase": margin_inc,
                    "candidates": r["candidates"],
                })
        except Exception as e:
            print(f"[WARN] analyze {code}: {e}", file=sys.stderr)
        time.sleep(0.1)
    return all_results


def format_summary(results: list[dict], target_date: str, days_history: int) -> str:
    lines = [f"🎯 主力雷達 — 分點+融資連動 {target_date}（{days_history} 日視窗）\n"]
    if not results:
        lines.append("無符合條件的標的（連續買超分點 + 融資同步增加 + 相關係數 ≥0.5）")
        return "\n".join(lines)

    # Sort overall by best correlation across stocks
    results.sort(key=lambda x: -max(c["correlation"] for c in x["candidates"]))

    lines.append(f"共篩出 {len(results)} 檔有「分點+融資雙連動」訊號\n")
    for r in results[:15]:
        lines.append(f"━━ {r['code']} {r['name']} ━━")
        lines.append(f"融資餘額 {r['current_balance']:,}張 (區間變化 {r['margin_increase']:+,})")
        for c in r["candidates"][:3]:
            buy_days = ",".join(d[4:8] for d in c["buy_dates"])
            lines.append(f"  {c['broker_id']} {c['broker_name']}: "
                          f"{c['active_days']}天買超({buy_days}) 淨+{c['total_net']/1000:,.0f}張 corr {c['correlation']:.2f}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="分點+融資連動每日掃描")
    parser.add_argument("--top-n", type=int, default=100, help="掃描前 N 檔（依今日融資餘額排序）")
    parser.add_argument("--include-concept-strong", action="store_true", default=True,
                        help="同步加入概念動能評分 ≥70 的成分股（預設開啟）")
    parser.add_argument("--no-concept-strong", dest="include_concept_strong",
                        action="store_false", help="關閉概念動能加入")
    parser.add_argument("--concept-min-score", type=float, default=70.0,
                        help="概念動能最低評分門檻，預設 70")
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--min-corr", type=float, default=0.5)
    parser.add_argument("--min-days", type=int, default=3)
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--bot-token")
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--finmind-token")
    parser.add_argument("--analyze-only", action="store_true",
                        help="跳過 BSR 抓取，直接用快取做分析")
    parser.add_argument("--allow-margin-decrease", action="store_true",
                        help="允許區間融資餘額為負成長的標的入榜 (預設只保留正成長 = 主力建倉訊號)")
    args = parser.parse_args()

    bot_token = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")
    finmind_token = args.finmind_token or os.environ.get("FINMIND_TOKEN", "")
    if not finmind_token:
        print("[ERROR] need FINMIND_TOKEN", file=sys.stderr)
        sys.exit(1)

    target_date = datetime.now().strftime("%Y-%m-%d")

    print(f"【步驟 1/3】取得 Top {args.top_n} 大融資餘額股票...", file=sys.stderr)
    top_stocks = get_top_margin_increase_stocks(args.top_n)
    margin_codes = [c for c, _, _ in top_stocks]
    print(f"  融資餘額 Top {args.top_n}: {len(margin_codes)} 檔", file=sys.stderr)

    concept_codes = []
    if args.include_concept_strong:
        concept_codes = get_strong_concept_stocks(args.concept_min_score)
        print(f"  概念動能 ≥{args.concept_min_score:.0f} 分成份股: {len(concept_codes)} 檔",
              file=sys.stderr)

    codes = list(dict.fromkeys(margin_codes + concept_codes))
    extra = len(codes) - len(margin_codes)
    print(f"  合併目標: {len(codes)} 檔（融資 {len(margin_codes)} + 新增 {extra}）",
          file=sys.stderr)

    if not args.analyze_only:
        print(f"【步驟 2/3】抓 BSR 分點資料...", file=sys.stderr)
        scan_result = scan_and_save(codes)
        print(f"  成功 {scan_result['success']}/{len(codes)}", file=sys.stderr)

    print(f"【步驟 3/3】跑連動分析（{args.days} 日歷史）...", file=sys.stderr)
    results = analyze_all(codes, args.days, finmind_token,
                          min_corr=args.min_corr, min_days=args.min_days,
                          require_margin_increase=not args.allow_margin_decrease)
    print(f"  命中 {len(results)} 檔", file=sys.stderr)

    summary = format_summary(results, target_date, args.days)
    print(summary)

    if args.telegram:
        if not bot_token:
            print("[ERROR] need TG_BOT_TOKEN for --telegram", file=sys.stderr)
            sys.exit(1)
        send_telegram(summary, bot_token, args.chat_id)


if __name__ == "__main__":
    main()

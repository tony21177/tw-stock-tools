#!/usr/bin/env python3
"""每日 AI 分點行為敘事 → LINE 推播 (22:00 cron，三線資料全齊後).

流程：讀 chip_narrative_watchlist.json 的股票清單 → 逐檔抓當日 BSR
(tw_chip_price.analyze，已快取則直接用) → 產生完整版敘事
(chip_narrative，同日已有快取則直接重用、不重複消耗 Claude 用量) →
推 LINE (Messaging API push)。

LINE 憑證從環境變數讀：LINE_CHANNEL_TOKEN (Messaging API channel access
token) + LINE_USER_ID (加 bot 好友後的 userId)。未設定時退化成「只產生
敘事快取」(網頁 /chip-price 立即可看)，並在 log 註明。

用法:
  chip_narrative_push.py               # 全 watchlist，產生+推播
  chip_narrative_push.py --dry-run     # 產生但不推，印出訊息內容
  chip_narrative_push.py --codes 2313  # 只跑指定檔 (逗號分隔)

cron (22:00 平日，經 is_trading_day 守門):
  0 22 * * 1-5 ... is_trading_day.py && LINE_CHANNEL_TOKEN=... \
    LINE_USER_ID=... FINMIND_TOKEN=... python3 chip_narrative_push.py \
    >> chip_narrative_push.log 2>&1
"""
import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import line_push  # noqa: E402  (repo-root shared module)

WATCHLIST_PATH = os.path.join(HERE, "chip_narrative_watchlist.json")


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_watchlist() -> dict:
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("codes"):
        raise RuntimeError("watchlist codes 為空")
    cfg.setdefault("mode", "full")
    return cfg


def _strip_markdown(text: str) -> str:
    """LINE 是純文字 — 去掉敘事裡的 markdown 記號。"""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    t = re.sub(r"^#{1,3} ", "", t, flags=re.M)
    return t


# 切塊/推播/換發 token 皆由 repo-root 共用模組 line_push 提供
_split_chunks = line_push.split_chunks
push_line = line_push.push_text


# 融資約 21:00、借券賣出餘額 21:30 才公布當日值。敘事若在當日 21:30 前
# 產生，融資/借券當日資料不全（會寫「以前一日為準」）→ 推播端須重跑。
DATA_COMPLETE_HHMM = "2130"


def _cache_data_complete(cached: dict, date: str) -> bool:
    """快取是否用「當日完整資料」產生。

    敘事基準日 = date（YYYYMMDD）。當日融資/借券 21:30 後才齊，故：
      - generated_at 日期 > date  → 隔日以後產生，資料早已齊 → True
      - generated_at 日期 == date 且時間 ≥ 21:30 → True
      - generated_at 日期 == date 且時間 < 21:30 → False（盤中/傍晚產生，不全）
      - 無 generated_at → True（舊快取，不強迫重跑）
    """
    ga = cached.get("generated_at", "")
    if not ga:
        return True
    try:
        d_part, t_part = ga.split(" ")
        gdate = d_part.replace("-", "")
        ghhmm = t_part.replace(":", "")[:4]
    except (ValueError, IndexError):
        return True
    if gdate > date:
        return True
    if gdate == date:
        return ghhmm >= DATA_COMPLETE_HHMM
    return True   # 理論上不會 gdate < date（快取檔名綁 date）


def run_one(code: str, mode: str, token: str, recipients: list[str],
            dry_run: bool = False) -> bool:
    """單檔：確保當日 BSR → 產生(或重用)敘事 → 推給所有 LINE 收件者。"""
    import tw_chip_price
    import chip_narrative

    _log(f"--- {code} ---")
    data = tw_chip_price.analyze(code)     # 抓/用當日 BSR，推斷交易日
    if not data:
        _log(f"[ERROR] {code} BSR 無資料，跳過")
        return False
    date = data["date"]
    name = data.get("name", "")

    cached = chip_narrative.load_cached(code, date, mode)
    if cached and _cache_data_complete(cached, date):
        _log(f"{code} {date} 敘事已有快取（資料齊），直接重用 (不重跑)")
        result = cached
    else:
        if cached:
            _log(f"{code} {date} 快取為 21:30 資料公布前產生 "
                 f"({cached.get('generated_at')})、融資/借券當日資料不全 → 重跑")
        else:
            _log(f"{code} {date} 產生 {mode} 敘事中…")
        # 同步重跑（直接呼叫 _generate 覆寫快取，不走 detached start）
        chip_narrative._generate(code, date, mode)
        result = chip_narrative.load_cached(code, date, mode)
        if not result:
            st = chip_narrative.get_status(code, date, mode)
            _log(f"[ERROR] {code} 敘事失敗: {st.get('error', st)}")
            return False
        _log(f"{code} 敘事完成 ({result.get('elapsed_sec')}s)")

    header = (f"🤖 {code} {name} AI 籌碼敘事 "
              f"({date[:4]}/{date[4:6]}/{date[6:8]})")
    body = _strip_markdown(result["narrative"])
    text = f"{header}\n\n{body}"

    if dry_run:
        _log(f"[dry-run] 訊息 {len(text)} 字元，"
             f"{len(_split_chunks(text))} 塊，收件者 {recipients}：\n"
             f"{text[:300]}…")
        return True
    if not (token and recipients):
        _log(f"{code} 敘事已快取 (網頁可看)；LINE 未設定，不推播")
        return True
    ok = True
    for r in recipients:
        if push_line(text, token, r):
            _log(f"{code} 已推 LINE → {r[:6]}… ✅")
        else:
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--codes", help="逗號分隔，覆蓋 watchlist")
    args = ap.parse_args()

    cfg = load_watchlist()
    codes = ([c.strip() for c in args.codes.split(",") if c.strip()]
             if args.codes else cfg["codes"])
    mode = cfg.get("mode", "full")
    token = line_push.resolve_token()
    # 收件者：config line_recipients 優先，否則退回 env LINE_USER_ID
    recipients = cfg.get("line_recipients") or []
    env_uid = os.environ.get("LINE_USER_ID", "")
    if not recipients and env_uid:
        recipients = [env_uid]
    if not (token and recipients) and not args.dry_run:
        _log("[WARN] LINE 憑證/收件者未設定 (LINE_CHANNEL_TOKEN 或 "
             "LINE_CHANNEL_ID+LINE_CHANNEL_SECRET；收件者用 config "
             "line_recipients 或 env LINE_USER_ID) — 僅產生敘事快取，不推播")

    fails = 0
    for code in codes:      # 逐檔 sequential — 避免同時多個 claude 進程
        try:
            if not run_one(code, mode, token, recipients,
                           dry_run=args.dry_run):
                fails += 1
        except Exception as e:
            _log(f"[ERROR] {code} 未預期錯誤: {type(e).__name__}: {e}")
            fails += 1
    _log(f"完成 {len(codes) - fails}/{len(codes)} 檔")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

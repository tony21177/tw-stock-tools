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

WATCHLIST_PATH = os.path.join(HERE, "chip_narrative_watchlist.json")
LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"
LINE_TOKEN_API = "https://api.line.me/v2/oauth/accessToken"
LINE_TEXT_LIMIT = 4900   # 官方上限 5000，留 buffer


def mint_line_token(channel_id: str, channel_secret: str) -> str:
    """用 Channel ID + secret 換發 channel access token (效期 30 天)。

    每次執行都換新 → 不用管理 long-lived token 的過期問題。失敗回 ""。
    """
    import urllib.parse
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": channel_id,
        "client_secret": channel_secret,
    }).encode()
    req = urllib.request.Request(
        LINE_TOKEN_API, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp).get("access_token", "")
    except Exception as e:
        _log(f"[ERROR] LINE token 換發失敗: {e}")
        return ""


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


def _split_chunks(text: str, limit: int = LINE_TEXT_LIMIT) -> list[str]:
    """依段落切塊，每塊 ≤ limit 字元。"""
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        cand = (cur + "\n\n" + para) if cur else para
        if len(cand) <= limit:
            cur = cand
            continue
        if cur:
            chunks.append(cur)
        while len(para) > limit:          # 單段超長硬切
            chunks.append(para[:limit])
            para = para[limit:]
        cur = para
    if cur:
        chunks.append(cur)
    return chunks


def push_line(text: str, token: str, recipient: str) -> bool:
    """推一段文字到一個 LINE 收件者 (U=個人 / C=群組)，自動切塊。"""
    chunks = _split_chunks(text, LINE_TEXT_LIMIT)
    ok = True
    # Messaging API 一次 push 最多 5 messages
    for i in range(0, len(chunks), 5):
        payload = {
            "to": recipient,
            "messages": [{"type": "text", "text": c}
                         for c in chunks[i:i + 5]],
        }
        req = urllib.request.Request(
            LINE_PUSH_API,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
        except Exception as e:
            body = ""
            if hasattr(e, "read"):
                try:
                    body = e.read().decode()[:200]
                except Exception:
                    pass
            _log(f"[ERROR] LINE push 失敗: {e} {body}")
            ok = False
    return ok


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
    if cached:
        _log(f"{code} {date} 敘事已有快取，直接重用 (不重跑)")
        result = cached
    else:
        _log(f"{code} {date} 產生 {mode} 敘事中…")
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
    token = os.environ.get("LINE_CHANNEL_TOKEN", "")
    if not token:
        cid = os.environ.get("LINE_CHANNEL_ID", "")
        secret = os.environ.get("LINE_CHANNEL_SECRET", "")
        if cid and secret:
            token = mint_line_token(cid, secret)
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

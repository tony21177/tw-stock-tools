#!/usr/bin/env python3
"""LINE Messaging API 推播共用模組.

憑證兩種給法（擇一）：
  - LINE_CHANNEL_TOKEN：現成 channel access token
  - LINE_CHANNEL_ID + LINE_CHANNEL_SECRET：每次執行自動換發 token
    (POST /v2/oauth/accessToken，效期 30 天，免管理過期)

收件者 U 開頭=個人 1:1、C 開頭=群組。免費額度 200 則/月，每收件者
each 計一則（群組算 1 不論人數）。

用法:
    import line_push
    token = line_push.resolve_token()          # 讀環境變數
    line_push.push_text("hello", token, "C96e49...")
"""
import json
import os
import urllib.parse
import urllib.request

LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"
LINE_TOKEN_API = "https://api.line.me/v2/oauth/accessToken"
LINE_TEXT_LIMIT = 4900   # 官方上限 5000，留 buffer


def mint_token(channel_id: str, channel_secret: str) -> str:
    """用 Channel ID + secret 換發 access token。失敗回 ""。"""
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
        import sys
        print(f"[ERROR] LINE token 換發失敗: {e}", file=sys.stderr)
        return ""


def resolve_token() -> str:
    """從環境變數解析 token：LINE_CHANNEL_TOKEN 優先，否則 ID+secret 換發。"""
    token = os.environ.get("LINE_CHANNEL_TOKEN", "")
    if token:
        return token
    cid = os.environ.get("LINE_CHANNEL_ID", "")
    secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    if cid and secret:
        return mint_token(cid, secret)
    return ""


def split_chunks(text: str, limit: int = LINE_TEXT_LIMIT) -> list[str]:
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


def push_text(text: str, token: str, recipient: str) -> bool:
    """推一段文字給一個收件者，自動切塊 (單次 push 最多 5 則)。"""
    import sys
    chunks = split_chunks(text, LINE_TEXT_LIMIT)
    ok = True
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
            print(f"[ERROR] LINE push 失敗: {e} {body}", file=sys.stderr)
            ok = False
    return ok

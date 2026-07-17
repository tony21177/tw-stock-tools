#!/usr/bin/env python3
"""AI 分點行為敘事 — 把多日行為序列餵給 headless Claude CLI 產生敘事分析.

Web 按鈕 (app.py /chip-price) 觸發：組 prompt (序列 + 判讀紀律，紀律
源自 ~/.claude/skills/chip-price/SKILL.md 的行為序列判讀紀律) → 呼叫
`claude -p` → 存 cache/chip_narrative/{code}_{date}.json。狀態用同目錄
的 .status 檔管理，跨 process 安全（Flask 可能多 worker）。

每次產生 = 一次 Claude 訂閱/API 呼叫，故同 (code, date) 有 cache 就
直接回，除非 force。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

NARRATIVE_DIR = os.path.join(HERE, "cache", "chip_narrative")
CLAUDE_TIMEOUT = 300          # seconds
STALE_RUNNING_SEC = 420       # running 狀態超過 7 分鐘視為死掉，可重跑

_PROMPT_TEMPLATE = """你是台股籌碼分析師。以下是 {code} {name} {date_fmt} 的分點多日連續買賣序列。
格式說明：每分點一行序列，`MM/DD 淨買賣張數@位階%`；@% = 當日買(賣)均價在該日
高低區間的位階 (0%=貼著最低價成交, 100%=貼著最高價)；`—` = 該日無資料(非零買賣)；
k = 千張。

{series_text}

當日行情：開 ${o:.2f} / 高 ${h:.2f} / 低 ${l:.2f} / 收 ${c:.2f} ({chg:+.2f}%)，總量 {vol:,} 張。

請依下列紀律寫敘事分析（繁體中文）：
- 結構：🌏 外資動向 → 🏦 內資買賣分點逐個點名 → 🏠 散戶 → 📌 結論
- 隔日沖慣犯要看到完整 cycle（平日近零活動 → 某日高位階大買 → 隔日全倒）才能斷言；單日大賣不夠
- 分辨「真累積」（逐日同向、累計墊高）vs「沖來沖去」（逐日劇烈翻面、累計歸零）— 兩者都會出現單日大買，意義完全不同
- 低接 vs 追高看 @位階，連續多天低位階買 = 耐心低接
- 不可只挑符合敘事的分點：外資有人低接，要同時看有沒有外資在倒
- 外資分點含客戶委託非全為自營、散戶指標（永豐金/國泰敦南）為經驗 proxy — 結論措辭保留此不確定性
- 結論要把「今天的賣壓/買盤主體是誰」講清楚，並給出明天觀察重點
- 直接輸出分析，不要開場白、不要重複資料表"""


def _paths(code: str, date: str) -> tuple[str, str]:
    base = os.path.join(NARRATIVE_DIR, f"{code}_{date}")
    return base + ".json", base + ".status.json"


def _write_atomic(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_prompt(code: str, date: str) -> str:
    """Assemble the narrative prompt from the multi-day behavior series.

    Raises RuntimeError when no series data exists for (code, date).
    """
    import tw_chip_price as cp
    try:
        ohlc_map = cp._fetch_ohlc_map(code, date)
    except Exception:
        ohlc_map = {}
    view = cp.build_behavior_series(code, date, ohlc_map=ohlc_map)
    if not view:
        raise RuntimeError(f"{code} {date} 無分點序列資料 "
                           f"(bsr_cache 缺當日檔，先跑一次籌碼價量分析)")
    series_text = "\n".join(cp._format_behavior(view))
    ohlc = ohlc_map.get(date) or {}
    o = h = low = c = 0.0
    try:
        full = cp.get_ohlc(code, date)
        if full:
            o, h, low, c = (full["open"], full["high"],
                            full["low"], full["close"])
    except Exception:
        pass
    if not h:
        h, low, c = (ohlc.get("high", 0.0), ohlc.get("low", 0.0),
                     ohlc.get("close", 0.0))
        o = c
    chg = (c - o) / o * 100 if o else 0.0
    vol = 0
    try:
        stats = cp._load_day_broker_stats(code, date)
        vol = int(sum(s["buy"] for s in (stats or {}).values()) / 1000)
    except Exception:
        pass
    name = ""
    try:
        from stock_names import get_name
        name = get_name(code, "")
    except Exception:
        pass
    return _PROMPT_TEMPLATE.format(
        code=code, name=name, date_fmt=f"{date[:4]}/{date[4:6]}/{date[6:8]}",
        series_text=series_text, o=o, h=h, l=low, c=c, chg=chg, vol=vol)


def _run_claude(prompt: str) -> str:
    """Call headless Claude CLI; returns narrative text. Raises on failure."""
    claude = shutil.which("claude")
    if not claude:
        fallback = os.path.expanduser("~/.local/bin/claude")
        claude = fallback if os.path.exists(fallback) else None
    if not claude:
        raise RuntimeError("claude CLI 不存在 — 需安裝 Claude Code")
    proc = subprocess.run(
        [claude, "-p", "--output-format", "text"],
        input=prompt, capture_output=True, text=True,
        timeout=CLAUDE_TIMEOUT, cwd=REPO)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip()[:400]
        raise RuntimeError(f"claude exit {proc.returncode}: {err or '無輸出'}")
    return out


def load_cached(code: str, date: str) -> dict | None:
    """Return the finished narrative dict, or None."""
    result, _ = _paths(code, date)
    return _read_json(result)


def get_status(code: str, date: str) -> dict:
    """{state: none|running|done|error, ...}"""
    result_p, status_p = _paths(code, date)
    done = _read_json(result_p)
    if done:
        return {"state": "done", **done}
    st = _read_json(status_p)
    if st and st.get("state") == "running":
        if time.time() - st.get("started_at", 0) > STALE_RUNNING_SEC:
            return {"state": "error", "error": "上次執行逾時未完成，可重試"}
        return {"state": "running", "started_at": st.get("started_at")}
    if st and st.get("state") == "error":
        return st
    return {"state": "none"}


def _generate(code: str, date: str) -> None:
    """Worker: build prompt → claude → save. Errors land in status file."""
    result_p, status_p = _paths(code, date)
    try:
        prompt = build_prompt(code, date)
        t0 = time.time()
        text = _run_claude(prompt)
        _write_atomic(result_p, {
            "code": code, "date": date, "narrative": text,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 1),
        })
        try:
            os.remove(status_p)
        except OSError:
            pass
    except Exception as e:
        _write_atomic(status_p, {"state": "error",
                                 "error": f"{type(e).__name__}: {e}"})


def start(code: str, date: str, force: bool = False) -> dict:
    """Kick off narrative generation in a background thread (idempotent).

    Returns current status. With force=True, discards existing result.
    """
    result_p, status_p = _paths(code, date)
    st = get_status(code, date)
    if st["state"] == "running":
        return st
    if st["state"] == "done" and not force:
        return st
    if force:
        for p in (result_p,):
            try:
                os.remove(p)
            except OSError:
                pass
    _write_atomic(status_p, {"state": "running", "started_at": time.time()})
    threading.Thread(target=_generate, args=(code, date),
                     daemon=True).start()
    return {"state": "running", "started_at": time.time()}


if __name__ == "__main__":
    # CLI 測試: python3 chip_narrative.py 2313 20260716 [--prompt-only]
    _code, _date = sys.argv[1], sys.argv[2]
    if "--prompt-only" in sys.argv:
        print(build_prompt(_code, _date))
    else:
        _generate(_code, _date)
        print(json.dumps(get_status(_code, _date), ensure_ascii=False,
                         indent=1))

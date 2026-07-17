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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

NARRATIVE_DIR = os.path.join(HERE, "cache", "chip_narrative")

# quick = 純文字（只餵序列，無工具）；full = agentic（帶工具跑三線整合）
MODES = {
    "quick": {"timeout": 300, "stale": 420, "suffix": ""},
    "full": {"timeout": 1500, "stale": 1800, "suffix": "_full"},
}

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


_PROMPT_FULL_TEMPLATE = """你是台股籌碼分析師，工作目錄 {repo}（有 Bash/Read 等工具可用）。
目標：對 {code} {name} 以 {date_fmt} 為基準日做「三線整合 + 分點行為序列」完整籌碼分析，
最後只輸出一篇敘事判讀（不要輸出過程）。

規則：
- 先讀 ~/.claude/skills/chip/SKILL.md 與 ~/.claude/skills/chip-price/SKILL.md，
  遵守全部判讀紀律（30 天內除權息強制查核 — ⚠ 制度區分：只有「融券」有
  停止過戶日前強制回補；「借券賣出」不強制、借券人可付權益補償不還券，
  出借人召回才須還，故除息前還券潮 = 召回+自主驅動的常見現象 ≠ 主動撤退；
  借券≠賣空、還券≠平倉；隔日沖需完整 買→倒 cycle；
  真累積 vs 沖來沖去；不可只挑符合敘事的分點）
- FINMIND_TOKEN 從 `crontab -l` 解析
- 資料收集：
  1. `python3 tw_chip_price.py {code} --date {date} --no-fetch` — 當日 BSR 已有
     cache，讀完整 8 段報告，特別是【🧭 分點行為 — 近N日連續買賣序列】
  2. 借券/融資線：依 chip skill 流程抓借券餘額、SBL 賣空、融資維持率，
     並查 FinMind TaiwanStockDividend 確認 30 天內有無除權息事件
  3. 需要時查 FinMind 價量確認走勢背景
- 禁止：推 Telegram、寫入或修改任何檔案、跑 cron/systemctl、重抓 BSR 網站
  （只用既有 cache；--no-fetch 失敗就在敘事中明講缺當日 BSR）
- 任一條線抓不到就明講「缺」，不要編造數字

輸出（繁體中文，直接輸出、無開場白、不要重複原始資料表）：
🌏 外資動向 → 🏦 內資逐分點點名 → 🏠 散戶 → 🧷 借券/融資/除權息交叉檢核
→ 📌 結論（今天買賣壓主體是誰 + 明日觀察重點）"""


def _paths(code: str, date: str, mode: str = "quick") -> tuple[str, str]:
    base = os.path.join(NARRATIVE_DIR,
                        f"{code}_{date}{MODES[mode]['suffix']}")
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


def build_prompt_full(code: str, date: str) -> str:
    """Prompt for the agentic full run (三線整合). Same precondition as
    quick: the day's BSR cache must exist."""
    import tw_chip_price as cp
    if not cp._load_day_broker_stats(code, date):
        raise RuntimeError(f"{code} {date} 無分點序列資料 "
                           f"(bsr_cache 缺當日檔，先跑一次籌碼價量分析)")
    name = ""
    try:
        from stock_names import get_name
        name = get_name(code, "")
    except Exception:
        pass
    return _PROMPT_FULL_TEMPLATE.format(
        repo=REPO, code=code, name=name, date=date,
        date_fmt=f"{date[:4]}/{date[4:6]}/{date[6:8]}")


def _run_claude(prompt: str, mode: str = "quick") -> str:
    """Call headless Claude CLI; returns narrative text. Raises on failure.

    quick: 純文字單回合（無工具）。full: agentic，帶
    --dangerously-skip-permissions 讓它能跑 repo 內的查詢工具（僅本機
    自用 dashboard 觸發；prompt 已禁止寫檔/推播/抓站）。
    """
    claude = shutil.which("claude")
    if not claude:
        fallback = os.path.expanduser("~/.local/bin/claude")
        claude = fallback if os.path.exists(fallback) else None
    if not claude:
        raise RuntimeError("claude CLI 不存在 — 需安裝 Claude Code")
    cmd = [claude, "-p", "--output-format", "text"]
    if mode == "full":
        cmd.append("--dangerously-skip-permissions")
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True,
        timeout=MODES[mode]["timeout"], cwd=REPO)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip()[:400]
        raise RuntimeError(f"claude exit {proc.returncode}: {err or '無輸出'}")
    return out


def load_cached(code: str, date: str, mode: str = "quick") -> dict | None:
    """Return the finished narrative dict, or None."""
    result, _ = _paths(code, date, mode)
    return _read_json(result)


def get_status(code: str, date: str, mode: str = "quick") -> dict:
    """{state: none|running|done|error, ...}"""
    result_p, status_p = _paths(code, date, mode)
    done = _read_json(result_p)
    if done:
        return {"state": "done", "mode": mode, **done}
    st = _read_json(status_p)
    if st and st.get("state") == "running":
        if time.time() - st.get("started_at", 0) > MODES[mode]["stale"]:
            return {"state": "error", "mode": mode,
                    "error": "上次執行逾時未完成，可重試"}
        return {"state": "running", "mode": mode,
                "started_at": st.get("started_at")}
    if st and st.get("state") == "error":
        return {**st, "mode": mode}
    return {"state": "none", "mode": mode}


def _generate(code: str, date: str, mode: str = "quick") -> None:
    """Worker: build prompt → claude → save. Errors land in status file."""
    result_p, status_p = _paths(code, date, mode)
    try:
        prompt = (build_prompt_full(code, date) if mode == "full"
                  else build_prompt(code, date))
        t0 = time.time()
        text = _run_claude(prompt, mode)
        _write_atomic(result_p, {
            "code": code, "date": date, "mode": mode, "narrative": text,
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


def start(code: str, date: str, mode: str = "quick",
          force: bool = False) -> dict:
    """Kick off narrative generation in a background thread (idempotent).

    Returns current status. With force=True, discards existing result.
    """
    if mode not in MODES:
        return {"state": "error", "error": f"未知 mode: {mode}"}
    result_p, status_p = _paths(code, date, mode)
    st = get_status(code, date, mode)
    if st["state"] == "running":
        return st
    if st["state"] == "done" and not force:
        return st
    if force:
        try:
            os.remove(result_p)
        except OSError:
            pass
    _write_atomic(status_p, {"state": "running", "started_at": time.time()})
    # Detached subprocess (own session), NOT an in-process thread: a Flask
    # service restart would kill the thread mid-run and strand the status
    # file at "running" until stale timeout (happened 2026-07-17 deploying
    # while a 3491 full run was in flight). The CLI entrypoint of this
    # module runs _generate and writes the result/error files itself.
    cmd = [sys.executable, os.path.abspath(__file__), code, date]
    if mode == "full":
        cmd.append("--full")
    log_path = os.path.join(NARRATIVE_DIR, "worker.log")
    with open(log_path, "a") as lg:
        subprocess.Popen(cmd, stdout=lg, stderr=lg,
                         start_new_session=True, cwd=REPO)
    return {"state": "running", "mode": mode, "started_at": time.time()}


if __name__ == "__main__":
    # CLI 測試: python3 chip_narrative.py <code> <date> [--full] [--prompt-only]
    _code, _date = sys.argv[1], sys.argv[2]
    _mode = "full" if "--full" in sys.argv else "quick"
    if "--prompt-only" in sys.argv:
        print(build_prompt_full(_code, _date) if _mode == "full"
              else build_prompt(_code, _date))
    else:
        _generate(_code, _date, _mode)
        print(json.dumps(get_status(_code, _date, _mode), ensure_ascii=False,
                         indent=1))

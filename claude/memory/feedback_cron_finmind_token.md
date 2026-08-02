---
name: Cron 必須帶 FINMIND_TOKEN env var
description: tw_stock_tools 中所有用到 FinMind 的 cron 都必須在 cron line 顯式設 FINMIND_TOKEN=... 否則靜默失敗（0 stocks valid 但不報錯）
type: feedback
originSessionId: e67fcb4a-ba3e-4b10-8dd9-8d8a51bbed3d
---
當 tw_stock_tools 的任何工具遷移到 FinMind 作為資料源後，**crontab line 必須帶 FINMIND_TOKEN env var**。

**為什麼會踩**：之前 lending / concept_momentum 用 Yahoo / TWSE 不需要 token，crontab line 只有 `TG_BOT_TOKEN`。遷到 FinMind 後沒同步更新 crontab，導致：
- `fetch_stock()` 拿不到 token → 返回空 dict
- 整個 cron 跑完 0 stocks valid，但 script 不報錯
- Dashboard 顯示「無資料」但 daily.log 看起來沒問題

**Why:** FinMind 沒 token 會被視為 register tier (免費)，而 sponsor-only dataset (全市場一天 / 法人 / 融資總額 / 議借 / SBL) 都會回 4xx，被 fetcher catch 後返回空，導致全部資料失敗。

**How to apply:**
- 完成任何「Yahoo/TWSE → FinMind」遷移後**立刻檢查 crontab**對應 line 有沒有 `FINMIND_TOKEN=...`
- 範本 cron line：
  ```
  0 17 * * 1-5 TG_BOT_TOKEN=... FINMIND_TOKEN=eyJ0... /usr/bin/python3 /home/kun/project/.../script.py ... >> log 2>&1
  ```
- 用此指令快速 audit 所有 cron：
  ```bash
  crontab -l | grep -E "/usr/bin/python3.*\.py" | while read line; do
    schedule=$(echo "$line" | awk '{print $1, $2}')
    script=$(echo "$line" | grep -oE "[a-z_]+\.py" | head -1)
    has=$(echo "$line" | grep -c "FINMIND_TOKEN")
    if [ "$has" = "1" ]; then status="✓"; else status="❌"; fi
    echo "  $status  $schedule  $script"
  done
  ```

**現在 (2026-05-12) 應該全綠的 6 個 cron**：
- 07:30 tw_daily_screen.py (轉機接力 Layer 1+2)
- 07:40 tw_second_wave.py (強勢股第二波)
- 16:00 tw_lending_monitor.py --mode lending (借券雷達)
- 17:00 concept_momentum/run_daily.py (族群熱力 + 大盤寬度 + 主力/盤前/借券歷史榜)
- 18:00 tw_broker_monitor.py (主力雷達)
- 21:30 tw_lending_monitor.py --mode sbl (空頭撤退)

**踩過的歷史**：
- 2026-05-12: 17:00 concept_momentum cron 沒 token，5/12 dashboard 全空。同時 16:00 lending cron 也沒 token (同 bug)。Lending mode 5/12 cache 0 stocks (但不影響太多 — 借券資料早就在 finmind_client 中失敗了 — actually wait, lending_monitor 也是遷 FinMind 才壞的，跟 concept_momentum 同因).

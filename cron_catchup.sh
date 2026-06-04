#!/bin/bash
# WSL2 cron catch-up: WSL 被 Windows 暫停時 cron 那一分鐘不在跑就直接跳過、
# 不補跑 (例如 2026-06-03 傍晚 WSL 睡著，17:00 大盤寬度 + 18:00 主力雷達漏跑)。
#
# 本腳本 @reboot + 每小時 (09-23) 跑一次，檢查「今日該產出的 cron 輸出檔」
# 是否存在；缺檔 + 已過排程時間 + 今天是平日 → 補跑該 job。
# Idempotent: 檔案存在就跳過，所以重複跑安全。
#
# 只補「會產生當日 JSON 檔」的 job (dashboard / 歷史榜依賴這些)；chip-price /
# ADR 警示是純 Telegram 推播，不在此補 (避免推到過時內容)。

set -u
ROOT=/home/kun/project/tw_stock_tools
cd "$ROOT" || exit 1
LOG="$ROOT/cron_catchup.log"

# 單一執行鎖，避免 @reboot 與 hourly 重疊
exec 9>"$ROOT/.cron_catchup.lock"
flock -n 9 || exit 0

DOW=$(date +%u)              # 1=Mon .. 7=Sun
HOUR=$((10#$(date +%H)))     # 00-23
TODAY=$(date +%Y%m%d)
[ "$DOW" -gt 5 ] && exit 0   # 週末不跑 (台股休市)

# 從現有 crontab 動態抓 token (不硬編)
TG=$(crontab -l 2>/dev/null | grep -oE 'TG_BOT_TOKEN=[^ ]+' | head -1 | cut -d= -f2)
FM=$(crontab -l 2>/dev/null | grep -oE 'FINMIND_TOKEN=[^ ]+' | head -1 | cut -d= -f2)
PY=/usr/bin/python3
C="$ROOT/concept_momentum/cache"

log() { echo "[catchup $(date '+%Y-%m-%d %H:%M')] $*" >> "$LOG"; }

# run_if_missing <輸出檔> <排程時 (過了才補)> <log 檔> -- <指令...>
run_if_missing() {
  local out="$1" after="$2" jlog="$3"; shift 3; shift  # drop the "--"
  [ -f "$out" ] && return 0
  [ "$HOUR" -lt "$after" ] && return 0   # 還沒到排程時間，交給正常 cron
  log "缺 $(basename "$out") → 補跑: $*"
  TG_BOT_TOKEN="$TG" FINMIND_TOKEN="$FM" "$@" >> "$jlog" 2>&1
  log "補跑結束 (exit $?): $(basename "$out")"
}

# 07:30 轉機接力
run_if_missing "$C/turnaround_relay_history/$TODAY.json" 8 "$ROOT/daily_screen.log" -- \
  $PY "$ROOT/tw_daily_screen.py" --json-out "$C/turnaround_relay_history/$TODAY.json"
# 07:40 強勢股第二波
run_if_missing "$C/second_wave_history/$TODAY.json" 8 "$ROOT/second_wave.log" -- \
  $PY "$ROOT/tw_second_wave.py" --quiet --telegram --json-out "$C/second_wave_history/$TODAY.json"
# 16:00 借券動向
run_if_missing "$C/lending_radar_history/$TODAY.json" 17 "$ROOT/lending_monitor.log" -- \
  $PY "$ROOT/tw_lending_monitor.py" --mode lending --telegram --json-out-lending "$C/lending_radar_history/$TODAY.json"
# 17:00 概念動能 / 大盤寬度
run_if_missing "$C/results/analysis_$TODAY.json" 18 "$ROOT/concept_momentum/daily.log" -- \
  $PY "$ROOT/concept_momentum/run_daily.py" --telegram
# 18:00 主力雷達
run_if_missing "$C/broker_radar_history/$TODAY.json" 19 "$ROOT/broker_monitor.log" -- \
  $PY "$ROOT/tw_broker_monitor.py" --top-n 200 --telegram --json-out "$C/broker_radar_history/$TODAY.json"
# 21:30 借券賣出餘額
run_if_missing "$C/short_retreat_history/$TODAY.json" 22 "$ROOT/lending_monitor.log" -- \
  $PY "$ROOT/tw_lending_monitor.py" --mode sbl --telegram --json-out-sbl "$C/short_retreat_history/$TODAY.json"

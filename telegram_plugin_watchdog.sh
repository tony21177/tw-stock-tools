#!/bin/bash
# Telegram plugin (bun server.ts) busy-loop 看門狗。
# 背景:claude-plugins-official/telegram 0.0.6 有卡死 bug —
#   2026-07-30 起某 session 的 server 連續 7 天吃滿一顆 CPU(正常 idle ~3%)。
#   官方尚無新版,先用看門狗自癒:連續兩次檢查(cron 每 30 分)CPU>90% 即 kill,
#   session 下次互動會自動重啟 plugin server。
# cron:*/30 * * * * /home/kun/project/tw_stock_tools/telegram_plugin_watchdog.sh
STATE=/tmp/tg_plugin_watchdog.state
LOG=/home/kun/project/tw_stock_tools/telegram_watchdog.log

declare -A prev
if [ -f "$STATE" ]; then
  while read -r pid; do prev[$pid]=1; done < "$STATE"
fi
: > "$STATE"

for pid in $(pgrep -f "bun server.ts"); do
  # 確認是 telegram plugin 的 server
  cwd=$(readlink /proc/$pid/cwd 2>/dev/null)
  [[ "$cwd" == *"plugins"*"telegram"* ]] || continue
  cpu=$(ps -o pcpu= -p "$pid" | tr -d ' ' | cut -d. -f1)
  [ -z "$cpu" ] && continue
  if [ "$cpu" -gt 90 ]; then
    if [ -n "${prev[$pid]}" ]; then
      kill -9 "$pid"
      echo "$(date '+%F %T') KILL pid=$pid cpu=${cpu}% (連續兩次 >90%,busy-loop)" >> "$LOG"
    else
      echo "$pid" >> "$STATE"
      echo "$(date '+%F %T') WARN pid=$pid cpu=${cpu}% (首次,下次仍高則 kill)" >> "$LOG"
    fi
  fi
done
exit 0
